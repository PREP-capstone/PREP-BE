"""수익 구조(BM) 추천 API(/api/v1/business-model/recommend) 회귀 테스트. 작업 #7(3번 담당).

bm_mapping 시드 데이터가 필요한 케이스는 @pytest.mark.db로 표시한다.
"""

import pytest
from sqlalchemy import delete

from app.api.analysis_sessions import AnalysisSession, CreateAnalysisSessionRequest, create_analysis_session
from app.api.business_model import (
    BmRecommendation,
    BusinessModelRequest,
    BusinessModelResult,
    _precedent_service_names,
    recommend_business_model,
)
from app.db.session import AsyncSessionLocal


async def _create_session(**overrides) -> str:
    request = CreateAnalysisSessionRequest(
        service_name="bm-test", service_description="d", **overrides
    )
    response = await create_analysis_session(request)
    return response.result.session_id


async def _delete_session(session_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(AnalysisSession).where(AnalysisSession.session_id == session_id))
        await session.commit()


@pytest.mark.db
async def test_recommend_returns_404_for_unknown_session() -> None:
    response = await recommend_business_model(BusinessModelRequest(session_id="does-not-exist"))
    assert response.status_code == 404


@pytest.mark.db
async def test_recommend_is_insufficient_data_without_category_axes() -> None:
    # category_1/category_2가 없는 세션은 bm_mapping 조회 키가 없어 곧장
    # insufficient_data여야 한다 — 판정엔진_개발설계서.md §9.2: "지표 판정 없음,
    # 추천만 제공" 원칙과 같은 이유로 임의 추천을 만들면 안 된다.
    session_id = await _create_session()
    try:
        response = await recommend_business_model(BusinessModelRequest(session_id=session_id))
        assert response.result.match_level == "insufficient_data"
        assert response.result.recommendations == []
    finally:
        await _delete_session(session_id)


@pytest.mark.db
async def test_recommend_limits_to_two_cards() -> None:
    session_id = await _create_session(
        category_1="수면", category_2="정보제공", target="20대", service_type="앱"
    )
    try:
        response = await recommend_business_model(BusinessModelRequest(session_id=session_id))
        assert len(response.result.recommendations) <= 2
    finally:
        await _delete_session(session_id)


def test_business_model_result_hides_internal_frequency_and_match_label_from_json() -> None:
    result = BusinessModelResult(
        match_level="exact_match",
        match_scope_description="카테고리, 세부 기능, 타깃, 서비스 형태가 모두 같은 선례를 기준으로 비교했습니다.",
        recommendations=[
            BmRecommendation(
                bm_pattern="Subscription",
                frequency_score=3,
                frequency_score_global=5,
                precedent_level="많음",
                precedent_services=["삼성헬스", "눔"],
                bm_description="월간 또는 연간 구독료를 받고 지속적인 관리 기능을 제공하는 모델입니다.",
                contributing_competitor_ids="삼성헬스,눔",
            )
        ],
    )

    payload = result.model_dump()
    recommendation = payload["recommendations"][0]

    assert "match_level" not in payload
    assert "frequency_score" not in recommendation
    assert "frequency_score_global" not in recommendation
    assert "contributing_competitor_ids" not in recommendation
    assert recommendation["precedent_services"] == ["삼성헬스", "눔"]


def test_precedent_service_names_resolves_competitor_ids() -> None:
    names = _precedent_service_names(
        ["comp_samsung_health", "comp_noom", "comp_samsung_health"],
        {"comp_samsung_health": "삼성헬스", "comp_noom": "눔"},
    )

    assert names == ["삼성헬스", "눔"]
