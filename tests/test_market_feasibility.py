"""시장 현실성 판단 API(/api/v1/feasibility/market) 회귀 테스트. 작업 #7(3번 담당).

경쟁사/BM 시드 데이터가 필요한 케이스는 @pytest.mark.db로 표시한다.
"""

import pytest
from sqlalchemy import delete

from app.api.analysis_sessions import (
    AnalysisSession,
    CreateAnalysisSessionRequest,
    create_analysis_session,
    generate_session_id,
)
from app.api.feasibility import (
    MarketFeasibilityRequest,
    _badge_for_tier,
    _saturation_for_count,
    assess_market_feasibility,
)
from app.db.session import AsyncSessionLocal


def test_saturation_thresholds_match_design_doc() -> None:
    # 판정엔진_개발설계서.md §8.1/§8.4 — 0~2 Opportunity/높음, 3~4 Challenging/중간, 5+ Saturated/낮음.
    assert _saturation_for_count(0, platform_exists=False) == "Opportunity"
    assert _saturation_for_count(2, platform_exists=False) == "Opportunity"
    assert _saturation_for_count(3, platform_exists=False) == "Challenging"
    assert _saturation_for_count(4, platform_exists=False) == "Challenging"
    assert _saturation_for_count(5, platform_exists=False) == "Saturated"
    assert _saturation_for_count(5, platform_exists=True) == "Saturated"


def test_badge_reflects_platform_tier() -> None:
    assert _badge_for_tier("플랫폼") == "차별화 필요"
    assert _badge_for_tier("버티컬") == "진입 가능"
    assert _badge_for_tier(None) == "진입 가능"


def test_market_feasibility_request_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        MarketFeasibilityRequest.model_validate({"session_id": "s", "category_1": "수면"})


async def _create_session(**overrides) -> str:
    overrides.setdefault("category_1", "수면")
    request = CreateAnalysisSessionRequest(
        service_name="market-test", service_description="d", **overrides
    )
    response = await create_analysis_session(request)
    return response.result.session_id


async def _create_session_without_category() -> str:
    """category_1 필수화(요청 스키마) 이전에 만들어진 레거시 세션을 재현한다 —
    DB 컬럼은 여전히 nullable이라 ORM으로 직접 넣어야 이 상태를 만들 수 있다."""
    session_id = generate_session_id()
    async with AsyncSessionLocal() as session:
        session.add(
            AnalysisSession(
                session_id=session_id,
                service_name="market-test-no-category",
                service_description="d",
                target_users=[],
                service_type=None,
                processing_purpose=[],
                service_actions=[],
            )
        )
        await session.commit()
    return session_id


async def _delete_session(session_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(AnalysisSession).where(AnalysisSession.session_id == session_id))
        await session.commit()


@pytest.mark.db
async def test_market_feasibility_returns_404_for_unknown_session() -> None:
    response = await assess_market_feasibility(MarketFeasibilityRequest(session_id="does-not-exist"))
    assert response.status_code == 404


@pytest.mark.db
async def test_market_feasibility_is_insufficient_data_without_category_axes() -> None:
    # category_1/category_2가 없는 세션(STEP 1 분류 미반영)은 조회 키가 없어
    # 곧장 insufficient_data여야 한다 — 임의로 Opportunity를 부여하면 안 된다.
    session_id = await _create_session_without_category()
    try:
        response = await assess_market_feasibility(MarketFeasibilityRequest(session_id=session_id))
        assert response.result.match_level == "insufficient_data"
        assert response.result.saturation is None
        assert response.result.competitor_cards == []
    finally:
        await _delete_session(session_id)
