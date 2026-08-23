"""통합 판정 오케스트레이션 API(/api/v1/analysis/evaluate) 회귀 테스트.

analysis_sessions/health_data_items 시드가 필요해 DB 접속을 요구한다.
FAIL 분기(판정엔진_개발설계서.md §5.4)와 PASS 분기 각각의 결합 결과를 확인한다.
"""

import pytest
from sqlalchemy import delete

from app.api.analysis_sessions import (
    AnalysisSession,
    CreateAnalysisSessionRequest,
    HealthDataUpsertRequest,
    create_analysis_session,
    create_health_data,
)
from app.api.evaluate import EvaluateRequest, evaluate_analysis
from app.db.session import AsyncSessionLocal
from app.schemas.common import HealthDataItemInput

pytestmark = pytest.mark.db


async def _create_session(
    service_description: str,
    items: list[HealthDataItemInput],
    service_actions: list[str] | None = None,
) -> str:
    request = CreateAnalysisSessionRequest(
        service_name="evaluate-test", service_description=service_description, category_1="여성건강"
    )
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


async def test_evaluate_fail_branch_disables_market_and_business_model() -> None:
    """침습적 하드체크 FAIL 세션 — gate/regulatory-risk/correction-candidates는 채워지고
    데이터확보/시장현실성/수익구조는 전부 None이어야 한다."""
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
        response = await evaluate_analysis(EvaluateRequest(session_id=session_id))
        assert response.result.gate.verdict == "FAIL"
        assert response.result.regulatory_risk is not None
        assert response.result.correction_candidates is not None
        assert response.result.data_feasibility is None
        assert response.result.market_feasibility is None
        assert response.result.business_model is None
    finally:
        await _delete_session(session_id)


async def test_evaluate_pass_branch_fills_all_six() -> None:
    """생체지표+단순기록 PASS 세션 — 6개 필드 전부 값이 채워져야 한다
    (market/business_model은 시드 매칭이 없으면 insufficient_data일 수 있지만 None은 아님)."""
    session_id = await _create_session(
        "사용자가 측정한 심박수를 기록하고 히스토리로 조회한다.",
        [HealthDataItemInput(name="심박수", data_type="numeric", unit="bpm", source="user_input")],
        service_actions=["record"],
    )
    try:
        response = await evaluate_analysis(EvaluateRequest(session_id=session_id))
        assert response.result.gate.verdict == "PASS"
        assert response.result.regulatory_risk is not None
        assert response.result.correction_candidates is not None
        assert response.result.data_feasibility is not None
        assert response.result.market_feasibility is not None
        assert response.result.business_model is not None
    finally:
        await _delete_session(session_id)


async def test_evaluate_returns_404_for_unknown_session() -> None:
    response = await evaluate_analysis(EvaluateRequest(session_id="no_such_session"))
    assert response.status_code == 404
