"""수익 구조(BM) 추천 API. 작업 #7(3번 담당) — 판정엔진_개발설계서.md §9.

session_id로 analysis_sessions를 조회해 category_1/category_2/target/service_type을
조회 키로 bm_mapping을 완화 조회한다(§8.2/§9.1 4단계 전략 공유, app/domain/market_lookup.py).

bm_mapping은 저장 테이블이 아니라 competitors를 집계하는 값이므로(§9.1) 이 API는
등급을 매기지 않는다 — 판정엔진_개발설계서.md §9.2: "지표 판정 없음, 추천만 제공".
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select

from app.db.models import AnalysisSession, BmMapping, Competitor
from app.db.session import AsyncSessionLocal
from app.domain.market_lookup import CategoryKeys, MatchLevel, describe_match_level, relaxation_stages
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/v1/business-model", tags=["business-model"])

_RECOMMENDATION_LIMIT = 2


class BusinessModelRequest(BaseModel):
    # feasibility.py의 FeasibilityRequest/MarketFeasibilityRequest와 동일하게
    # extra="forbid" — 예전 명세의 필드를 실수로 같이 보내도 조용히 무시하지 않고
    # 422로 막는다.
    model_config = ConfigDict(extra="forbid")

    session_id: str


class BmRecommendation(BaseModel):
    bm_pattern: str | None
    frequency_score: int | None = Field(exclude=True)
    frequency_score_global: int | None = Field(exclude=True)
    precedent_level: str | None
    precedent_services: list[str]
    bm_description: str | None
    contributing_competitor_ids: str | None = Field(exclude=True)


class BusinessModelResult(BaseModel):
    match_level: MatchLevel = Field(exclude=True)
    match_scope_description: str
    recommendations: list[BmRecommendation]


class BusinessModelResponse(ApiResponse):
    result: BusinessModelResult


class BusinessModelErrorResponse(ApiResponse):
    result: None = None


_BM_DESCRIPTIONS: dict[str, str] = {
    "Freemium": "기본 기능은 무료로 제공하고 고급 기능이나 추가 분석을 유료로 전환하는 모델입니다.",
    "Subscription": "월간 또는 연간 구독료를 받고 지속적인 관리 기능을 제공하는 모델입니다.",
    "Add-on": "기본 서비스 위에 리포트, 코칭, 기기 연동 같은 부가 기능을 추가 판매하는 모델입니다.",
    "Lock-in": "사용자 데이터와 루틴이 쌓일수록 같은 서비스를 계속 쓰게 되는 구조를 만드는 모델입니다.",
    "Two-sided Market": "사용자와 전문가, 기관, 판매자 등 두 집단을 연결하고 중개 가치를 만드는 모델입니다.",
    "Pay Per Use": "검사, 분석, 리포트처럼 실제 사용한 기능 단위로 과금하는 모델입니다.",
    "Sensor As A Service": "센서나 웨어러블 연동 데이터를 기반으로 지속적인 모니터링 가치를 제공하는 모델입니다.",
    "Leverage Customer Data": "사용자 동의 기반 데이터를 분석해 개인화, 리포트, 제휴 가치로 확장하는 모델입니다.",
    "Digitization": "오프라인 관리나 상담 과정을 디지털 서비스로 전환해 비용과 접근성을 개선하는 모델입니다.",
    "Self-service": "사용자가 직접 기록, 확인, 관리하도록 만들어 운영 비용을 줄이는 모델입니다.",
    "Performance-based Contracting": "성과나 개선 결과에 따라 비용을 받는 모델입니다.",
    "Razor And Blade": "기기나 기본 서비스를 진입점으로 제공하고 소모품, 콘텐츠, 추가 기능에서 반복 매출을 만드는 모델입니다.",
}


def _split_competitor_refs(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


async def _find_competitor_names(session, competitor_refs: set[str]) -> dict[str, str]:
    if not competitor_refs:
        return {}
    rows = (
        await session.execute(
            select(Competitor.competitor_id, Competitor.name)
            .where(Competitor.competitor_id.in_(competitor_refs))
            .order_by(Competitor.competitor_id)
        )
    ).all()
    return {competitor_id: name for competitor_id, name in rows}


def _precedent_service_names(competitor_refs: list[str], competitor_names: dict[str, str]) -> list[str]:
    names: list[str] = []
    for competitor_ref in competitor_refs:
        name = competitor_names.get(competitor_ref, competitor_ref)
        if name not in names:
            names.append(name)
    return names


def _bm_description(pattern: str | None) -> str | None:
    if pattern is None:
        return None
    return _BM_DESCRIPTIONS.get(pattern)


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
        competitor_refs_by_mapping = {
            row.mapping_id: _split_competitor_refs(row.contributing_competitor_ids)
            for row in rows
        }
        competitor_refs = {
            competitor_ref
            for refs in competitor_refs_by_mapping.values()
            for competitor_ref in refs
        }
        competitor_names = await _find_competitor_names(session, competitor_refs)

    return BusinessModelResponse(
        isSuccess=True,
        code="BUSINESS_MODEL_RECOMMENDED",
        message="검증 필요 — 근거 부족" if match_level == "insufficient_data" else "수익 구조 추천이 완료되었습니다.",
        result=BusinessModelResult(
            match_level=match_level,
            match_scope_description=describe_match_level(match_level),
            recommendations=[
                BmRecommendation(
                    bm_pattern=row.bm_pattern,
                    frequency_score=row.frequency_score,
                    frequency_score_global=row.frequency_score_global,
                    precedent_level=row.precedent_level,
                    precedent_services=_precedent_service_names(
                        competitor_refs_by_mapping[row.mapping_id], competitor_names
                    ),
                    bm_description=_bm_description(row.bm_pattern),
                    contributing_competitor_ids=row.contributing_competitor_ids,
                )
                for row in rows
            ],
        ),
    )
