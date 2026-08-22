"""수익 구조(BM) 추천 API(/api/v1/business-model/recommend) 회귀 테스트. 작업 #7(3번 담당).

bm_mapping 시드 데이터가 필요한 케이스는 @pytest.mark.db로 표시한다.
"""

import pytest
from sqlalchemy import delete

from app.api.analysis_sessions import AnalysisSession, CreateAnalysisSessionRequest, create_analysis_session
from app.api.business_model import BusinessModelRequest, recommend_business_model
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
