"""데이터 확보 가능성 판단 API. 이슈 #38.

session_id로 analysis_sessions/health_data_items를 조회해 판단한다 — 별도 요청
바디로 데이터 목록을 다시 받지 않는다(judgement API와 동일하게 HealthDataItemInput을
저장 시점 스키마로 재사용하는 흐름).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.domain.health_data import SOURCE_TO_ACQUIRE_METHOD, is_biomarker_name, load_biomarker_keywords
from app.domain.market_lookup import CategoryKeys, MatchLevel, describe_match_level, relaxation_stages
from app.domain.scoring import grade_by_threshold
from app.domain.trend_client import assess_domestic_demand
from app.db.models import (
    AnalysisSession,
    ApiCatalog,
    BmMapping,
    CollectionDifficulty,
    Competitor,
    DataDifficulty,
    DataSensitivity,
    HealthDataItem,
    MvpStrategyTemplate,
    PublicDataCatalog,
    StandardScale,
)
from app.db.session import AsyncSessionLocal
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/v1/feasibility", tags=["feasibility"])


class FeasibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str


class AvailableSource(BaseModel):
    data_name: str
    source_type: Literal["public_api", "external_api"]
    source_name: str


class PrivacyRisk(BaseModel):
    data_name: str
    reason: str


class StandardScaleCandidate(BaseModel):
    scale_id: str
    name: str
    full_name: str | None
    category_1: str | None
    item_count: int | None
    scoring_range: str | None
    license_type: str | None
    source_url: str | None
    note: str | None


class MvpRoadmapStep(BaseModel):
    stage: int
    title: str
    description: str


class DataFeasibilityResult(BaseModel):
    data_feasibility_score: int
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    available_sources: list[AvailableSource]
    privacy_risks: list[PrivacyRisk]
    standard_scale_candidates: list[StandardScaleCandidate]
    mvp_roadmap: list[MvpRoadmapStep]


class DataFeasibilityResponse(ApiResponse):
    result: DataFeasibilityResult


class FeasibilityErrorResponse(ApiResponse):
    result: None = None


def _not_found_response() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=FeasibilityErrorResponse(
            isSuccess=False,
            code="ANALYSIS_SESSION_NOT_FOUND",
            message="분석 세션을 찾을 수 없습니다.",
        ).model_dump(),
    )


def _no_health_data_response() -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content=FeasibilityErrorResponse(
            isSuccess=False,
            code="HEALTH_DATA_REQUIRED",
            message="등록된 검진 데이터가 없습니다. 먼저 health-data를 등록해주세요.",
        ).model_dump(),
    )


def _risk_level_for_score(score: int) -> Literal["LOW", "MEDIUM", "HIGH"]:
    # db_구축_설계서.md §3.4 등급: 1~3 쉬움 / 4~10 보통 / 12~30 어려움.
    return grade_by_threshold(score, 3, 10, ("LOW", "MEDIUM", "HIGH"))


def _difficulty_level_for_risk(risk_level: Literal["LOW", "MEDIUM", "HIGH"]) -> str:
    return {"LOW": "쉬움", "MEDIUM": "보통", "HIGH": "어려움"}[risk_level]


def _classify_item_data_type(item: HealthDataItem, biomarker_keywords: set[str]) -> str:
    # judgement.py._classify_data_type과 같은 생체지표 사전을 쓴다 — 여긴 항목별로
    # 개별 판정해야 해서(D×S는 항목당 최댓값 채택) 그 함수를 그대로 못 쓰고 판별
    # 규칙만 재사용한다.
    return "생체지표" if is_biomarker_name(item.name, biomarker_keywords) else "라이프스타일"


def _privacy_reason(row: DataSensitivity) -> str:
    if row.requires_separate_consent:
        basis = f"{row.legal_basis_doc} {row.legal_basis_article}".strip()
        return f"별도 동의가 필요한 민감정보입니다({basis})." if basis else "별도 동의가 필요한 민감정보입니다."
    if row.note:
        return row.note
    return "개인정보 처리 기준 검토가 필요한 항목입니다."


def _tokens_overlap_with_name(field_value: str | None, name: str) -> bool:
    """field_value(콤마/JSON 배열로 여러 키워드가 든 필드)의 토큰 중 하나라도
    name과 겹치면 True.

    단순히 `name in field_value`만 보면 "공복혈당" 같은 복합어가 카탈로그의
    "혈당" 토큰과 안 겹친다고 판정된다(부분 문자열 방향이 반대). 그렇다고
    `field_value in name`만 보면 카탈로그의 긴 설명 문자열이 짧은 name에 안
    들어가 항상 실패한다. 토큰 단위로 쪼개서 양방향으로 봐야 "공복혈당" ⊃ "혈당"
    같은 케이스를 잡는다 — 다만 토큰이 아주 짧으면(1글자 등) 여전히 과매칭
    가능성이 있는 근사치 매칭이라는 한계는 남는다.
    """
    if not field_value:
        return False
    tokens = [t.strip(' []"') for t in field_value.replace(",", " ").split()]
    return any(len(token) >= 2 and (token in name or name in token) for token in tokens)


async def _find_available_sources(session, items: list[HealthDataItem]) -> list[AvailableSource]:
    """공공데이터/API 카탈로그에서 항목명과 매칭되는 걸 찾는다.

    item_code 같은 정확 매칭 키가 카탈로그 쪽에 없어서 토큰 단위 부분 문자열
    매칭이다 — data_sensitivity.item_code 매칭(정확)과 달리 근사치라는 점을
    인지하고 쓸 것. 더 정확히 하려면 카탈로그에 공용 코드를 추가해야 한다.
    카탈로그 규모가 작아(api_catalog 10건대, public_data_catalog 100건대) DB
    필터 대신 전체를 읽어와 Python에서 토큰 비교한다.
    """
    api_rows = (await session.execute(select(ApiCatalog))).scalars().all()
    public_rows = (await session.execute(select(PublicDataCatalog))).scalars().all()

    sources: list[AvailableSource] = []
    for item in items:
        api_row = next(
            (row for row in api_rows if _tokens_overlap_with_name(row.available_data_types, item.name)),
            None,
        )
        if api_row is not None:
            sources.append(
                AvailableSource(data_name=item.name, source_type="external_api", source_name=api_row.name)
            )
            continue

        public_row = next(
            (
                row
                for row in public_rows
                if _tokens_overlap_with_name(row.category_1_tags, item.name)
                or _tokens_overlap_with_name(row.name, item.name)
            ),
            None,
        )
        if public_row is not None:
            sources.append(
                AvailableSource(
                    data_name=item.name,
                    source_type="public_api",
                    source_name=public_row.org or public_row.name,
                )
            )

    return sources


async def _find_standard_scale_candidates(
    session,
    analysis_session: AnalysisSession,
    items: list[HealthDataItem],
) -> list[StandardScaleCandidate]:
    """standard_scales에서 자가입력 대체 근거 후보를 찾는다.

    1차 테이블은 공용 item_code가 없어서 category_1 exact match와 항목명/척도 설명의
    토큰 overlap을 같이 쓴다. 라이선스는 후보 정보로만 노출하고, 사용 가능 확정 판단은
    리포트/기획 단계에서 별도 확인한다.
    """
    rows = (await session.execute(select(StandardScale))).scalars().all()
    user_input_items = [item for item in items if item.source == "user_input"]

    scored: list[tuple[int, StandardScale]] = []
    for row in rows:
        score = 0
        if analysis_session.category_1 and row.category_1 == analysis_session.category_1:
            score += 3

        searchable = " ".join(
            value
            for value in [
                row.name,
                row.full_name,
                row.category_1,
                row.scoring_range,
                row.note,
            ]
            if value
        )
        if any(_tokens_overlap_with_name(searchable, item.name) for item in user_input_items):
            score += 2
        if score > 0:
            scored.append((score, row))

    scored.sort(key=lambda item: (-item[0], item[1].name))
    return [
        StandardScaleCandidate(
            scale_id=row.scale_id,
            name=row.name,
            full_name=row.full_name,
            category_1=row.category_1,
            item_count=row.item_count,
            scoring_range=row.scoring_range,
            license_type=row.license_type,
            source_url=row.source_url,
            note=row.note,
        )
        for _, row in scored[:3]
    ]


async def _find_mvp_roadmap(
    session,
    category_1: str | None,
    risk_level: Literal["LOW", "MEDIUM", "HIGH"],
) -> list[MvpRoadmapStep]:
    difficulty_level = _difficulty_level_for_risk(risk_level)

    category_by_stage: dict[int, MvpStrategyTemplate] = {}
    if category_1:
        category_rows = (
            await session.execute(
                select(MvpStrategyTemplate)
                .where(MvpStrategyTemplate.difficulty_level == difficulty_level)
                .where(MvpStrategyTemplate.category_1 == category_1)
                .order_by(MvpStrategyTemplate.stage, MvpStrategyTemplate.template_id)
            )
        ).scalars().all()
        category_by_stage = {row.stage: row for row in category_rows}

    common_rows = (
        await session.execute(
            select(MvpStrategyTemplate)
            .where(MvpStrategyTemplate.difficulty_level == difficulty_level)
            .where(MvpStrategyTemplate.category_1.is_(None))
            .order_by(MvpStrategyTemplate.stage, MvpStrategyTemplate.template_id)
        )
    ).scalars().all()
    common_by_stage = {row.stage: row for row in common_rows}

    rows = [
        row
        for stage in sorted(set(category_by_stage) | set(common_by_stage))
        if (row := category_by_stage.get(stage) or common_by_stage.get(stage)) is not None
    ]
    return [
        MvpRoadmapStep(stage=row.stage, title=row.title, description=row.description)
        for row in rows
    ]


@router.post(
    "/data",
    response_model=DataFeasibilityResponse,
    responses={
        404: {"model": FeasibilityErrorResponse},
        409: {"model": FeasibilityErrorResponse},
    },
)
async def assess_data_feasibility(
    request: FeasibilityRequest,
) -> DataFeasibilityResponse | JSONResponse:
    async with AsyncSessionLocal() as session:
        analysis_session = await session.get(AnalysisSession, request.session_id)
        if analysis_session is None:
            return _not_found_response()

        items = (
            await session.execute(
                select(HealthDataItem).where(HealthDataItem.session_id == request.session_id)
            )
        ).scalars().all()
        if not items:
            return _no_health_data_response()

        d_weight_by_type = {
            row.data_type: row.weight for row in (await session.execute(select(DataDifficulty))).scalars()
        }
        s_weight_by_method = {
            row.method: row.weight
            for row in (await session.execute(select(CollectionDifficulty))).scalars()
        }

        biomarker_keywords = await load_biomarker_keywords(session)

        max_score = 0
        for item in items:
            data_type = _classify_item_data_type(item, biomarker_keywords)
            method = SOURCE_TO_ACQUIRE_METHOD.get(item.source)
            if method is None:
                return JSONResponse(
                    status_code=500,
                    content=FeasibilityErrorResponse(
                        isSuccess=False,
                        code="FEASIBILITY_UNKNOWN_DATA_SOURCE",
                        message=f"지원하지 않는 데이터 수집 방법입니다: {item.source}",
                    ).model_dump(),
                )
            if data_type not in d_weight_by_type or method not in s_weight_by_method:
                return JSONResponse(
                    status_code=500,
                    content=FeasibilityErrorResponse(
                        isSuccess=False,
                        code="FEASIBILITY_REFERENCE_DATA_MISSING",
                        message="난이도 기준표(data_difficulty/collection_difficulty)가 시드되지 않았습니다.",
                    ).model_dump(),
                )
            max_score = max(max_score, d_weight_by_type[data_type] * s_weight_by_method[method])

        item_codes = {item.item_code for item in items if item.item_code}
        sensitivity_by_code = {}
        if item_codes:
            sensitivity_by_code = {
                row.item_code: row
                for row in (
                    await session.execute(
                        select(DataSensitivity).where(DataSensitivity.item_code.in_(item_codes))
                    )
                ).scalars()
            }

        privacy_risks: list[PrivacyRisk] = []
        for item in items:
            if item.item_code in sensitivity_by_code:
                privacy_risks.append(
                    PrivacyRisk(
                        data_name=item.name,
                        reason=_privacy_reason(sensitivity_by_code[item.item_code]),
                    )
                )
            elif item.is_sensitive:
                privacy_risks.append(
                    PrivacyRisk(
                        data_name=item.name,
                        reason="건강정보에 해당할 수 있어 민감정보 처리 기준 검토 필요",
                    )
                )

        available_sources = await _find_available_sources(session, items)
        risk_level = _risk_level_for_score(max_score)
        standard_scale_candidates = await _find_standard_scale_candidates(session, analysis_session, items)
        mvp_roadmap = await _find_mvp_roadmap(session, analysis_session.category_1, risk_level)

    return DataFeasibilityResponse(
        isSuccess=True,
        code="DATA_FEASIBILITY_COMPLETED",
        message="데이터 확보 가능성 판단이 완료되었습니다.",
        result=DataFeasibilityResult(
            data_feasibility_score=max_score,
            risk_level=risk_level,
            available_sources=available_sources,
            privacy_risks=privacy_risks,
            standard_scale_candidates=standard_scale_candidates,
            mvp_roadmap=mvp_roadmap,
        ),
    )


# ── 시장 현실성(§03) — 작업 #7(3번 담당). 판정엔진_개발설계서.md §8. ──────────────
#
# 국내 수요 판단근거 ①은 app_store_ranking(팀이 유료 API/비공식 수집 이슈로 보류,
# Notion "웰니스 창업 아이디어 검진 시스템" §8)은 여전히 범위 밖이지만, 검색
# 트렌드(app/domain/trend_client.py)는 2026-08-24부로 연결했다. 다만 원래 3단계
# (급성장/완만/하락) 설계가 실측 임계값 음수 이상치로 무너져 2단계(상위권/하위권)로
# 단순화한 상태라, 이 해석 자체가 여전히 팀 재검토 대상이다 — trend_client.py 모듈
# docstring 참고.

_COMPETITOR_CARD_LIMIT = 3
_SATURATED_THRESHOLD = 5
_CHALLENGING_THRESHOLD = 3
_PLATFORM_TIER = "플랫폼"

Saturation = Literal["Opportunity", "Challenging", "Saturated"]
MarketRealismGrade = Literal["높음", "중간", "낮음"]

_SATURATION_TO_GRADE: dict[Saturation, MarketRealismGrade] = {
    "Opportunity": "높음",
    "Challenging": "중간",
    "Saturated": "낮음",
}


class MarketFeasibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str


class CompetitorCard(BaseModel):
    name: str
    feature: str | None
    limitation: str | None
    badge: Literal["진입 가능", "차별화 필요"]


class MarketFeasibilityResult(BaseModel):
    match_level: MatchLevel = Field(exclude=True)
    match_scope_description: str
    competitor_count: int = Field(exclude=True)
    saturation: Saturation | None
    market_realism_grade: MarketRealismGrade | None
    platform_competitor_exists: bool
    platform_competitor_summary: str
    payment_precedent: str | None
    competitor_cards: list[CompetitorCard]
    # 판단근거① 국내 수요 — Naver 키 없음/호출 실패/임계값 미시딩이면 None
    # (app/domain/trend_client.py 참고). match_level과 무관하게 category_1만 있으면
    # 계산 시도한다 — 경쟁사 매칭과 검색 트렌드는 서로 다른 데이터 소스라서.
    domestic_demand: Literal["상위권", "하위권"] | None


class MarketFeasibilityResponse(ApiResponse):
    result: MarketFeasibilityResult


def _platform_competitor_summary(platform_exists: bool) -> str:
    if platform_exists:
        return "유사 범위 안에 플랫폼급 경쟁사가 있어 차별화 근거를 더 강하게 제시해야 합니다."
    return "유사 범위 안에 플랫폼급 경쟁사는 확인되지 않았습니다."


def _saturation_for_count(count: int, platform_exists: bool) -> Saturation:
    # 판정엔진_개발설계서.md §8.1 — 포화도가 낮을수록 시장현실성은 높다(역관계).
    # n>=5는 항상 Saturated로 분류하되(§8.4 신호등 매핑에 별도 "후보" 등급이 없음),
    # platform_competitor_exists로 "개수만으로 낮음"과 "대형 플랫폼까지 확인된 낮음"을
    # 구분해 리포트에서 근거 신뢰도를 드러낸다.
    if count <= _CHALLENGING_THRESHOLD - 1:
        return "Opportunity"
    if count < _SATURATED_THRESHOLD:
        return "Challenging"
    return "Saturated"


def _badge_for_tier(tier: str | None) -> Literal["진입 가능", "차별화 필요"]:
    # 배지 기준(§8.5)은 "대형 서비스가 동일 기능 제공 시 차별화 필요"라 원래 LLM/사람
    # 판단 영역에 가깝다. 규칙 기반 근사치로 tier='플랫폼'이면 차별화 필요, 아니면
    # 진입 가능으로 처리한다 — advertising_score와 같은 종류의 한계가 있다.
    return "차별화 필요" if tier == _PLATFORM_TIER else "진입 가능"


async def _find_competitors(session, keys: CategoryKeys) -> tuple[MatchLevel, list[Competitor]]:
    for match_level, filters in relaxation_stages(Competitor, keys):
        rows = (await session.execute(select(Competitor).where(*filters))).scalars().all()
        if rows:
            return match_level, list(rows)
    return "insufficient_data", []


async def _find_payment_precedent(session, keys: CategoryKeys) -> str | None:
    for _, filters in relaxation_stages(BmMapping, keys):
        row = (
            await session.execute(
                select(BmMapping.precedent_level)
                .where(*filters)
                .where(BmMapping.precedent_level.is_not(None))
                .order_by(BmMapping.frequency_score.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is not None:
            return row
    return None


@router.post(
    "/market",
    response_model=MarketFeasibilityResponse,
    responses={404: {"model": FeasibilityErrorResponse}},
)
async def assess_market_feasibility(
    request: MarketFeasibilityRequest,
) -> MarketFeasibilityResponse | JSONResponse:
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

        match_level, competitors = await _find_competitors(session, keys)
        payment_precedent = await _find_payment_precedent(session, keys)

    # 경쟁사 매칭(DB)과 검색 트렌드(외부 API)는 서로 다른 소스라 match_level과
    # 무관하게 category_1만 있으면 독립적으로 계산한다.
    domestic_demand = await assess_domestic_demand(keys.category_1)

    if match_level == "insufficient_data":
        return MarketFeasibilityResponse(
            isSuccess=True,
            code="MARKET_FEASIBILITY_INSUFFICIENT_DATA",
            message="유사 경쟁사 데이터가 부족해 시장 현실성을 판단할 수 없습니다.",
            result=MarketFeasibilityResult(
                match_level=match_level,
                match_scope_description=describe_match_level(match_level),
                competitor_count=0,
                saturation=None,
                market_realism_grade=None,
                platform_competitor_exists=False,
                platform_competitor_summary=_platform_competitor_summary(False),
                payment_precedent=payment_precedent,
                competitor_cards=[],
                domestic_demand=domestic_demand,
            ),
        )

    competitor_count = len(competitors)
    platform_exists = any(row.tier == _PLATFORM_TIER for row in competitors)
    saturation = _saturation_for_count(competitor_count, platform_exists)

    return MarketFeasibilityResponse(
        isSuccess=True,
        code="MARKET_FEASIBILITY_COMPLETED",
        message="시장 현실성 판단이 완료되었습니다.",
        result=MarketFeasibilityResult(
            match_level=match_level,
            match_scope_description=describe_match_level(match_level),
            competitor_count=competitor_count,
            saturation=saturation,
            market_realism_grade=_SATURATION_TO_GRADE[saturation],
            platform_competitor_exists=platform_exists,
            platform_competitor_summary=_platform_competitor_summary(platform_exists),
            payment_precedent=payment_precedent,
            competitor_cards=[
                CompetitorCard(
                    name=row.name,
                    feature=row.core_tags,
                    limitation=row.limitation,
                    badge=_badge_for_tier(row.tier),
                )
                for row in competitors[:_COMPETITOR_CARD_LIMIT]
            ],
            domestic_demand=domestic_demand,
        ),
    )
