"""judgement API 3종을 session_id 기반으로 호출하는 회귀 테스트. 이슈 #42.

analysis_sessions/health_data_items 시드가 필요해 DB 접속을 요구한다. 세션 생성은
feasibility.py 테스트(test_feasibility.py)와 같은 패턴 — create_analysis_session/
create_health_data를 직접 호출해 세션을 만들고 끝나면 지운다.
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
from app.api.judgement import GateRequest, judge_correction_candidates, judge_gate, judge_regulatory_risk
from app.db.session import AsyncSessionLocal
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
