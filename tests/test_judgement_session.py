"""judgement API 3종을 session_id 기반으로 호출하는 회귀 테스트. 이슈 #42.

analysis_sessions/health_data_items 시드가 필요해 DB 접속을 요구한다. 세션 생성은
feasibility.py 테스트(test_feasibility.py)와 같은 패턴 — create_analysis_session/
create_health_data를 직접 호출해 세션을 만들고 끝나면 지운다.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.responses import JSONResponse
from sqlalchemy import delete

from app.api.analysis_sessions import (
    AnalysisSession,
    CreateAnalysisSessionRequest,
    HealthDataUpsertRequest,
    create_analysis_session,
    create_health_data,
)
from app.api.judgement import GateRequest, judge_correction_candidates, judge_gate, judge_regulatory_risk
from app.db.session import AsyncSessionLocal
from app.domain.correction_llm import LLMUnavailable
from app.pipeline.gate_matrix_table import (
    HARDCHECK_AVOIDANCE_CERTIFICATION,
    HARDCHECK_AVOIDANCE_REDESIGN,
)
from app.schemas.common import HealthDataItemInput

pytestmark = pytest.mark.db


async def _create_session(
    service_description: str,
    items: list[HealthDataItemInput],
    service_actions: list[str] | None = None,
) -> str:
    request = CreateAnalysisSessionRequest(service_name="session-judgement-test", service_description=service_description)
    response = await create_analysis_session(request)
    session_id = response.result.session_id
    await create_health_data(
        session_id,
        HealthDataUpsertRequest(health_data_items=items, service_actions=service_actions),
    )
    return session_id


async def _delete_session(session_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(AnalysisSession).where(AnalysisSession.session_id == session_id))
        await session.commit()


async def test_gate_uses_stored_health_data_and_service_actions() -> None:
    """심박수(BIOMARKER_EXTRA)+record → 생체지표/단순기록/PASS, mock_requests.json의
    "생체지표_단순기록_PASS" 케이스와 같은 조합."""
    session_id = await _create_session(
        "사용자가 측정한 심박수를 기록하고 히스토리로 조회한다.",
        [HealthDataItemInput(name="심박수", data_type="numeric", unit="bpm", source="user_input")],
        service_actions=["record"],
    )
    try:
        response = await judge_gate(GateRequest(session_id=session_id))
        assert response.data_type == "생체지표"
        assert response.function_type == "단순기록"
        assert response.verdict == "PASS"
        assert response.avoidance_redesign is None
        assert response.avoidance_certification is None
        assert len(response.reasoning) == 4
        assert "하드체크 대상이 아닙니다" in response.reasoning[0]
    finally:
        await _delete_session(session_id)


async def test_gate_returns_conditional_for_biomarker_trend_analysis() -> None:
    """생체지표(BIOMARKER_EXTRA) + 비교·추이분석(visualize_trend) 조합은 CONDITIONAL.

    "심박수"를 쓰는 이유는 test_gate_uses_stored_health_data_and_service_actions와
    동일 — gate_keywords 시드 여부와 무관하게 항상 생체지표로 분류돼야 한다.
    """
    session_id = await _create_session(
        "사용자가 측정한 심박수의 변화 추이를 그래프로 시각화한다.",
        [HealthDataItemInput(name="심박수", data_type="numeric", unit="bpm", source="user_input")],
        service_actions=["record", "visualize_trend"],
    )
    try:
        response = await judge_gate(GateRequest(session_id=session_id))
        assert response.data_type == "생체지표"
        assert response.function_type == "비교·추이분석"
        assert response.verdict == "CONDITIONAL"
        assert response.avoidance_redesign is None
        assert response.avoidance_certification is None
        assert "조건부 통과(CONDITIONAL)" in response.reasoning[-1]
    finally:
        await _delete_session(session_id)


async def test_gate_fails_on_invasive_device_sync_hardcheck() -> None:
    """기기연동 + 침습적 신호 조합은 하드체크로 FAIL.

    생체지표 분류는 "심박수"(BIOMARKER_EXTRA)로 고정해 gate_keywords 시드와 무관하게
    만든다. invasive_signal은 detect_invasive()가 텍스트(CGM/연속혈당)만 보고
    판단해서 원래도 DB 의존이 아니다 — service_description은 그대로 유지.
    """
    session_id = await _create_session(
        "CGM 연속혈당측정기와 연동해 심박수를 실시간으로 기록한다.",
        [
            HealthDataItemInput(
                name="심박수", data_type="numeric", unit="bpm", source="device_sync",
                is_sensitive=True, item_code="sensitive_001",
            )
        ],
        service_actions=["record"],
    )
    try:
        response = await judge_gate(GateRequest(session_id=session_id))
        assert response.verdict == "FAIL"
        assert response.hardcheck_fired is True
        # 하드체크 FAIL은 매트릭스를 안 거치므로 avoidance 문구도 하드체크 전용 상수여야 한다(D-2).
        assert response.avoidance_redesign == HARDCHECK_AVOIDANCE_REDESIGN
        assert response.avoidance_certification == HARDCHECK_AVOIDANCE_CERTIFICATION
        assert "하드체크로 FAIL 판정" in response.reasoning[-1]
        assert "침습적 신호가 감지됐습니다" in response.reasoning[2]
    finally:
        await _delete_session(session_id)


async def test_gate_fails_via_matrix_for_biomarker_prediction_without_hardcheck() -> None:
    """생체지표+수치예측·진단(수동입력, 기기연동 아님)은 하드체크 없이 매트릭스 조회만으로 FAIL.

    device_sync가 아니라 user_input을 써서 하드체크(기기연동 필요)가 아닌 매트릭스 FAIL
    경로를 타도록 한다 — test_gate_fails_on_invasive_device_sync_hardcheck와 다른 코드 경로.
    avoidance 문구도 매트릭스 FAIL 경로에서 채워지는지 같이 검증한다.
    """
    session_id = await _create_session(
        "사용자가 측정한 심박수 수치를 예측해서 알려준다.",
        [HealthDataItemInput(name="심박수", data_type="numeric", unit="bpm", source="user_input")],
        service_actions=["predict"],
    )
    try:
        response = await judge_gate(GateRequest(session_id=session_id))
        assert response.data_type == "생체지표"
        assert response.function_type == "수치예측·진단"
        assert response.verdict == "FAIL"
        assert response.hardcheck_fired is False
        assert response.avoidance_redesign is not None
        assert response.avoidance_certification is not None
        assert "가장 높은 조합" in response.reasoning[1]
        assert "매트릭스 기준" in response.reasoning[-1]
    finally:
        await _delete_session(session_id)


async def test_gate_reasoning_explains_device_sync_without_invasive_signal() -> None:
    """생체지표+기기연동인데 침습 신호가 없어 하드체크를 피한 경우도 그 이유가 명시돼야 한다."""
    session_id = await _create_session(
        "사용자가 측정한 심박수를 기록한다.",
        [HealthDataItemInput(name="심박수", data_type="numeric", unit="bpm", source="device_sync")],
        service_actions=["record"],
    )
    try:
        response = await judge_gate(GateRequest(session_id=session_id))
        assert response.verdict == "PASS"
        assert response.hardcheck_fired is False
        assert "침습적 신호는 감지되지 않아 하드체크 대상이 아닙니다" in response.reasoning[0]
    finally:
        await _delete_session(session_id)


async def test_regulatory_risk_computes_privacy_score_from_stored_item_code() -> None:
    session_id = await _create_session(
        "사용자의 복용약물을 기록하고 관리한다.",
        [HealthDataItemInput(name="복용약물", data_type="text", source="user_input", item_code="sensitive_004")],
    )
    try:
        response = await judge_regulatory_risk(GateRequest(session_id=session_id))
        assert response.privacy_score == 3
        assert response.privacy_grade == "높음"
    finally:
        await _delete_session(session_id)


async def test_regulatory_risk_fills_applicable_laws_from_service_type() -> None:
    request = CreateAnalysisSessionRequest(
        service_name="service-law-map-test",
        service_description="심박수를 기록한다.",
        category_1="수면",
        service_type="기기연동",
    )
    session_id = (await create_analysis_session(request)).result.session_id
    await create_health_data(
        session_id,
        HealthDataUpsertRequest(
            health_data_items=[HealthDataItemInput(name="심박수", data_type="numeric", source="user_input")]
        ),
    )
    try:
        response = await judge_regulatory_risk(GateRequest(session_id=session_id))
        assert "kr-medical-device-act-20260701" in response.applicable_laws
        assert response.service_law_description
    finally:
        await _delete_session(session_id)


async def test_regulatory_risk_applicable_laws_empty_without_service_type() -> None:
    session_id = await _create_session(
        "심박수를 기록한다.",
        [HealthDataItemInput(name="심박수", data_type="numeric", source="user_input")],
    )
    try:
        response = await judge_regulatory_risk(GateRequest(session_id=session_id))
        assert response.applicable_laws == []
        assert response.service_law_description is None
    finally:
        await _delete_session(session_id)


async def test_correction_candidates_matches_stored_service_description() -> None:
    session_id = await _create_session(
        "사용자에게 복약지도를 제공하고 복용 시간을 알려준다.",
        [HealthDataItemInput(name="복용약물", data_type="text", source="user_input")],
    )
    try:
        response = await judge_correction_candidates(GateRequest(session_id=session_id))
        assert any(c.risky_text == "복약지도" for c in response.candidates)
    finally:
        await _delete_session(session_id)


async def test_correction_candidates_does_not_require_health_data() -> None:
    """correction-candidates는 service_description만 쓰고 health_data_items를
    참조하지 않으므로, health-data 미등록 세션이어도 409 없이 동작해야 한다."""
    request = CreateAnalysisSessionRequest(
        service_name="no-health-data-test", service_description="사용자에게 복약지도를 제공한다."
    )
    session_id = (await create_analysis_session(request)).result.session_id
    try:
        response = await judge_correction_candidates(GateRequest(session_id=session_id))
        assert not isinstance(response, JSONResponse)
        assert any(c.risky_text == "복약지도" for c in response.candidates)
    finally:
        await _delete_session(session_id)


async def test_correction_candidates_skips_llm_fallback_when_rule_based_matches_exist() -> None:
    """규칙 기반 매칭이 있으면 LLM①을 아예 호출하지 않아야 한다(이슈 #58, 비용 절감 요건)."""
    session_id = await _create_session(
        "사용자에게 복약지도를 제공하고 복용 시간을 알려준다.",
        [HealthDataItemInput(name="복용약물", data_type="text", source="user_input")],
    )
    try:
        with patch(
            "app.api.judgement.generate_correction_candidates", new_callable=AsyncMock
        ) as mock_llm:
            response = await judge_correction_candidates(GateRequest(session_id=session_id))
        mock_llm.assert_not_called()
        assert any(c.risky_text == "복약지도" for c in response.candidates)
    finally:
        await _delete_session(session_id)


async def test_correction_candidates_calls_llm_fallback_when_no_rule_based_match() -> None:
    """규칙 기반 매칭이 0건이면 LLM①을 호출하고, 그 결과를 exact_phrase_match=False로 채운다."""
    session_id = await _create_session(
        "사용자가 매일 마신 물의 양을 기록하고 알림을 받는다.",
        [HealthDataItemInput(name="음수량", data_type="numeric", source="user_input")],
    )
    llm_result = [
        {
            "risky_text": "약 시간표를 짜드려요",
            "safe_text": "복약 알림을 보내드려요",
            "legal_basis": {"document_id": "kr-pharmaceutical-affairs-act-20260621", "article": "제2조"},
        }
    ]
    try:
        with (
            patch("app.api.judgement._match_correction_rules", new=AsyncMock(return_value=[])),
            patch(
                "app.api.judgement.generate_correction_candidates",
                new=AsyncMock(return_value=llm_result),
            ) as mock_llm,
        ):
            response = await judge_correction_candidates(GateRequest(session_id=session_id))
        mock_llm.assert_called_once()
        assert len(response.candidates) == 1
        candidate = response.candidates[0]
        assert candidate.risky_text == "약 시간표를 짜드려요"
        assert candidate.safe_text == "복약 알림을 보내드려요"
        assert candidate.exact_phrase_match is False
        assert candidate.legal_basis.document_id == "kr-pharmaceutical-affairs-act-20260621"
    finally:
        await _delete_session(session_id)


async def test_correction_candidates_returns_empty_when_llm_fallback_unavailable() -> None:
    """규칙 기반 0건 + LLM도 실패(LLMUnavailable)면 500이 아니라 빈 리스트로 정상 응답해야 한다."""
    session_id = await _create_session(
        "사용자가 매일 마신 물의 양을 기록하고 알림을 받는다.",
        [HealthDataItemInput(name="음수량", data_type="numeric", source="user_input")],
    )
    try:
        with (
            patch("app.api.judgement._match_correction_rules", new=AsyncMock(return_value=[])),
            patch(
                "app.api.judgement.generate_correction_candidates",
                new=AsyncMock(side_effect=LLMUnavailable("테스트: OPENAI_API_KEY 없음")),
            ),
        ):
            response = await judge_correction_candidates(GateRequest(session_id=session_id))
        assert not isinstance(response, JSONResponse)
        assert response.candidates == []
    finally:
        await _delete_session(session_id)


async def test_gate_returns_404_for_unknown_session() -> None:
    response = await judge_gate(GateRequest(session_id="no_such_session"))
    assert response.status_code == 404


async def test_gate_returns_409_when_no_health_data_registered() -> None:
    request = CreateAnalysisSessionRequest(service_name="empty-session-test", service_description="d")
    session_id = (await create_analysis_session(request)).result.session_id
    try:
        response = await judge_gate(GateRequest(session_id=session_id))
        assert response.status_code == 409
    finally:
        await _delete_session(session_id)
