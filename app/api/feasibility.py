"""데이터 확보 가능성 판단 API. 이슈 #38.

session_id로 analysis_sessions/health_data_items를 조회해 판단한다 — 별도 요청
바디로 데이터 목록을 다시 받지 않는다(judgement API와 동일하게 HealthDataItemInput을
저장 시점 스키마로 재사용하는 흐름).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.judgement import _SOURCE_TO_ACQUIRE_METHOD, _biomarker_keywords
from app.db.models import (
    AnalysisSession,
    ApiCatalog,
    CollectionDifficulty,
    DataDifficulty,
    DataSensitivity,
    HealthDataItem,
    PublicDataCatalog,
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


class DataFeasibilityResult(BaseModel):
    data_feasibility_score: int
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    available_sources: list[AvailableSource]
    privacy_risks: list[PrivacyRisk]


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
    # API 계약에서는 프론트에서 안정적으로 비교하기 쉬운 영문 enum을 반환한다.
    if score <= 3:
        return "LOW"
    if score <= 10:
        return "MEDIUM"
    return "HIGH"


def _classify_item_data_type(item: HealthDataItem, biomarker_keywords: set[str]) -> str:
    # judgement.py._classify_data_type과 같은 생체지표 사전을 쓴다 — 여긴 항목별로
    # 개별 판정해야 해서(D×S는 항목당 최댓값 채택) 그 함수를 그대로 못 쓰고 판별
    # 규칙만 재사용한다.
    return "생체지표" if any(keyword in item.name for keyword in biomarker_keywords) else "라이프스타일"


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
    return any(token and (token in name or name in token) for token in tokens)


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

        biomarker_keywords = await _biomarker_keywords()

        max_score = 0
        for item in items:
            data_type = _classify_item_data_type(item, biomarker_keywords)
            method = _SOURCE_TO_ACQUIRE_METHOD.get(item.source)
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

    return DataFeasibilityResponse(
        isSuccess=True,
        code="DATA_FEASIBILITY_COMPLETED",
        message="데이터 확보 가능성 판단이 완료되었습니다.",
        result=DataFeasibilityResult(
            data_feasibility_score=max_score,
            risk_level=_risk_level_for_score(max_score),
            available_sources=available_sources,
            privacy_risks=privacy_risks,
        ),
    )
