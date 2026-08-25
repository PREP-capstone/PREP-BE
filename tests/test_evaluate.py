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
from app.api.evaluate import EvaluateRequest, _find_competitor_prices, _find_overall_actions, evaluate_analysis
from app.api.feasibility import DataFeasibilityResult, MarketFeasibilityResult
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
        assert response.result.session.session_id == session_id
        assert response.result.session.category_1 == "여성건강"
        assert response.result.gate.verdict == "FAIL"
        assert response.result.regulatory_risk is not None
        assert response.result.correction_candidates is not None
        assert response.result.data_feasibility is None
        assert response.result.market_feasibility is None
        assert response.result.business_model is None
        assert any(link.target_section == "SECTION 2-1 규제 위험도" for link in response.result.section_links)
        assert any("GATE FAIL" in action.action_text for action in response.result.next_actions)
        assert any(action.action_text.startswith("개인정보 보호법") for action in response.result.next_actions)
        # FAIL 분기는 data_feasibility/market_feasibility가 None이라(§5.4) 공통(무관)
        # 트리거만 매칭돼야 한다 — data_level/market_level 조건은 안 걸려야 함.
        assert response.result.overall_actions
        assert {a.tag for a in response.result.overall_actions} <= {"[지금 당장]", "[출시 전 필수]"}
    finally:
        await _delete_session(session_id)


@pytest.mark.llm
async def test_evaluate_pass_branch_fills_all_six() -> None:
    """생체지표+단순기록 PASS 세션 — 6개 필드 전부 값이 채워져야 한다
    (market/business_model은 시드 매칭이 없으면 insufficient_data일 수 있지만 None은 아님).

    market_feasibility/business_model이 채워지면 differentiation_point·bm_card_summaries
    생성 시도도 함께 일어나 실제 OpenAI 호출이 나간다(app/api/evaluate.py) — 비용
    발생을 기본 실행에서 막기 위해 llm 마커를 붙인다. `-m "not llm"`이 기본값."""
    session_id = await _create_session(
        "사용자가 측정한 심박수를 기록하고 히스토리로 조회한다.",
        [HealthDataItemInput(name="심박수", data_type="numeric", unit="bpm", source="user_input")],
        service_actions=["record"],
    )
    try:
        response = await evaluate_analysis(EvaluateRequest(session_id=session_id))
        assert response.result.session.session_id == session_id
        assert response.result.session.health_data_items[0].name == "심박수"
        assert response.result.gate.verdict == "PASS"
        assert response.result.regulatory_risk is not None
        assert response.result.correction_candidates is not None
        assert response.result.data_feasibility is not None
        assert response.result.market_feasibility is not None
        assert response.result.business_model is not None
        assert any(link.target_section == "SECTION 1 GATE" for link in response.result.section_links)
        assert any("예측·진단" in action.action_text for action in response.result.next_actions)
        assert response.result.overall_actions
    finally:
        await _delete_session(session_id)


async def test_evaluate_returns_404_for_unknown_session() -> None:
    response = await evaluate_analysis(EvaluateRequest(session_id="no_such_session"))
    assert response.status_code == 404


def _data_feasibility(risk_level: str) -> DataFeasibilityResult:
    return DataFeasibilityResult(
        data_feasibility_score=1, risk_level=risk_level, available_sources=[], privacy_risks=[]
    )


def _market_feasibility(grade: str | None) -> MarketFeasibilityResult:
    return MarketFeasibilityResult(
        match_level="insufficient_data" if grade is None else "exact_match",
        competitor_count=0,
        saturation=None,
        market_realism_grade=grade,
        platform_competitor_exists=False,
        payment_precedent=None,
        competitor_cards=[],
        domestic_demand=None,
    )


@pytest.mark.db
async def test_find_overall_actions_matches_only_common_when_axes_are_none() -> None:
    # GATE FAIL 분기와 동일한 입력(둘 다 None) — data_level/market_level 트리거는
    # 걸리면 안 되고 공통(무관) 트리거만 매칭돼야 한다.
    actions = await _find_overall_actions(None, None)
    assert actions
    assert all(a.tag in ("[지금 당장]", "[출시 전 필수]") for a in actions)


@pytest.mark.db
async def test_find_overall_actions_maps_english_risk_level_to_korean_trigger() -> None:
    # data_feasibility.risk_level은 영문(LOW/MEDIUM/HIGH)인데 action_templates.trigger_value는
    # 국문(쉬움/보통/어려움)이라 매핑이 정확해야 매칭된다 — 안 맞으면 조용히 공통 항목만 나오고
    # data_level 트리거 액션(시드: act_data_hard_1/2)이 빠진다.
    actions = await _find_overall_actions(_data_feasibility("HIGH"), None)
    assert any("MVP" in a.action_text for a in actions)


@pytest.mark.db
async def test_find_overall_actions_caps_at_four_per_tag() -> None:
    actions = await _find_overall_actions(_data_feasibility("HIGH"), _market_feasibility("낮음"))
    by_tag: dict[str, int] = {}
    for action in actions:
        by_tag[action.tag] = by_tag.get(action.tag, 0) + 1
    assert all(count <= 4 for count in by_tag.values())


@pytest.mark.db
async def test_find_competitor_prices_is_deterministic_for_duplicate_names() -> None:
    # 코드 리뷰로 확인(2026-08-25) — competitors.name은 PK가 아니라 "삼성헬스"처럼
    # 동명 행이 실제로 여러 건(서로 다른 competitor_id, 가격도 다름) 존재한다.
    # 매 호출 같은 결과가 나와야 하고(비결정적 dict 덮어쓰기 금지), 빈 문자열
    # 가격 행이 있어도 다른 행의 실제 가격으로 채워져야 한다.
    first = await _find_competitor_prices({"삼성헬스"})
    second = await _find_competitor_prices({"삼성헬스"})
    assert first == second
    assert first.get("삼성헬스")
