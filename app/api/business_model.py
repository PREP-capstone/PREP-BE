"""수익 구조(BM) 추천 API. 작업 #7(3번 담당) — 판정엔진_개발설계서.md §9.

session_id로 analysis_sessions를 조회해 category_1/category_2/target/service_type을
조회 키로 bm_mapping을 완화 조회한다(§8.2/§9.1 4단계 전략 공유, app/domain/market_lookup.py).

bm_mapping은 저장 테이블이 아니라 competitors를 집계하는 값이므로(§9.1) 이 API는
등급을 매기지 않는다 — 판정엔진_개발설계서.md §9.2: "지표 판정 없음, 추천만 제공".
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import desc, select

from app.db.models import AnalysisSession, BmMapping
from app.db.session import AsyncSessionLocal
from app.domain.market_lookup import CategoryKeys, MatchLevel, relaxation_stages
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/v1/business-model", tags=["business-model"])

_RECOMMENDATION_LIMIT = 2


class BusinessModelRequest(BaseModel):
    session_id: str


class BmRecommendation(BaseModel):
    bm_pattern: str | None
    frequency_score: int | None
    frequency_score_global: int | None
    precedent_level: str | None
    contributing_competitor_ids: str | None


class BusinessModelResult(BaseModel):
    match_level: MatchLevel
    recommendations: list[BmRecommendation]


class BusinessModelResponse(ApiResponse):
    result: BusinessModelResult


class BusinessModelErrorResponse(ApiResponse):
    result: None = None


def _not_found_response() -> JSONResponse:
    # judgement.py/feasibility.py와 같은 코드·메시지 — 세션 조회 실패는 프론트가
    # 한 가지 방식으로만 처리하면 되게 통일한다.
    return JSONResponse(
        status_code=404,
        content=BusinessModelErrorResponse(
            isSuccess=False,
            code="ANALYSIS_SESSION_NOT_FOUND",
            message="분석 세션을 찾을 수 없습니다.",
        ).model_dump(),
    )


async def _find_recommendations(session, keys: CategoryKeys) -> tuple[MatchLevel, list[BmMapping]]:
    for match_level, filters in relaxation_stages(BmMapping, keys):
        rows = (
            await session.execute(
                select(BmMapping)
                .where(*filters)
                .order_by(desc(BmMapping.frequency_score))
                .limit(_RECOMMENDATION_LIMIT)
            )
        ).scalars().all()
        if rows:
            return match_level, list(rows)
    return "insufficient_data", []


@router.post(
    "/recommend",
    response_model=BusinessModelResponse,
    responses={404: {"model": BusinessModelErrorResponse}},
)
async def recommend_business_model(request: BusinessModelRequest) -> BusinessModelResponse | JSONResponse:
    async with AsyncSessionLocal() as session:
        analysis_session = await session.get(AnalysisSession, request.session_id)
        if analysis_session is None:
            return _not_found_response()

        keys = CategoryKeys(
            category_1=analysis_session.category_1,
            category_2=analysis_session.category_2,
            target=analysis_session.target,
            service_type=analysis_session.service_type,
        )
        match_level, rows = await _find_recommendations(session, keys)

    return BusinessModelResponse(
        isSuccess=True,
        code="BUSINESS_MODEL_RECOMMENDED",
        message="검증 필요 — 근거 부족" if match_level == "insufficient_data" else "수익 구조 추천이 완료되었습니다.",
        result=BusinessModelResult(
            match_level=match_level,
            recommendations=[
                BmRecommendation(
                    bm_pattern=row.bm_pattern,
                    frequency_score=row.frequency_score,
                    frequency_score_global=row.frequency_score_global,
                    precedent_level=row.precedent_level,
                    contributing_competitor_ids=row.contributing_competitor_ids,
                )
                for row in rows
            ],
        ),
    )
