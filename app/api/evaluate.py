"""통합 판정 오케스트레이션 API. gate 판정 결과로 나머지 5개 판정/추천 API를
조건부·병렬 호출해 하나의 응답으로 합친다 — 판정엔진_개발설계서.md §5.4 "GATE FAIL 분기".

session_id 하나만 받고 세션 요약(get_analysis_session_detail)·gate·regulatory-risk·
correction-candidates·feasibility 2종·business-model 전부 이 프로세스 안에서 함수로
직접 호출한다(HTTP 아님). 카테고리 분류(category-classifier/predict)는 호출하지
않는다 — 프론트가 STEP1→2 전환 시 별도로 호출하고, PATCH .../category로 세션에
반영한 뒤에 evaluate를 부르는 흐름을 전제로 한다.

section_links(section_link_rules, §15.8)는 gate_verdict/data_type/service_type 세 축을
동시에 봐야 해서 개별 서브 API가 아니라 여기서 직접 조회한다. FAIL 분기에도 계산한다 —
§5.4가 데이터확보/시장현실성/수익구조만 비활성화 대상으로 명시했지, section_links는
포함하지 않았고 gate/session 값만으로 계산 가능하기 때문(팀 재검토 대상으로 남겨둠).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select

from app.api.analysis_sessions import AnalysisSessionDetail, get_analysis_session_detail
from app.api.business_model import BusinessModelRequest, BusinessModelResult, recommend_business_model
from app.api.feasibility import (
    DataFeasibilityResult,
    FeasibilityRequest,
    MarketFeasibilityRequest,
    MarketFeasibilityResult,
    assess_data_feasibility,
    assess_market_feasibility,
)
from app.api.judgement import (
    CorrectionCandidatesResponse,
    GateRequest,
    GateResponse,
    RegulatoryRiskResponse,
    judge_correction_candidates,
    judge_gate,
    judge_regulatory_risk,
)
from app.db.models import SectionLinkRule
from app.db.session import AsyncSessionLocal
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


class SectionLink(BaseModel):
    target_section: str
    message: str


async def _find_section_links(gate: GateResponse, service_type: str | None) -> list[SectionLink]:
    """section_link_rules 조회 — gate_verdict/data_type/service_type 세 축을 동시에 봐야
    해서(판정엔진_개발설계서.md §15.8) 각 서브 API 안이 아니라 evaluate 레벨에서 조회한다."""
    conditions = [
        (SectionLinkRule.condition_type == "gate_verdict") & (SectionLinkRule.condition_value == gate.verdict),
        (SectionLinkRule.condition_type == "data_type") & (SectionLinkRule.condition_value == gate.data_type),
    ]
    if service_type:
        conditions.append(
            (SectionLinkRule.condition_type == "service_type") & (SectionLinkRule.condition_value == service_type)
        )
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(SectionLinkRule).where(or_(*conditions)))).scalars().all()
    return [SectionLink(target_section=row.target_section, message=row.message) for row in rows]


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str


class EvaluateResult(BaseModel):
    session: AnalysisSessionDetail
    gate: GateResponse
    regulatory_risk: RegulatoryRiskResponse
    correction_candidates: CorrectionCandidatesResponse
    # FAIL이면 데이터확보/시장현실성/수익구조는 비활성화(None) — §5.4.
    data_feasibility: DataFeasibilityResult | None
    market_feasibility: MarketFeasibilityResult | None
    business_model: BusinessModelResult | None
    section_links: list[SectionLink]


class EvaluateResponse(ApiResponse):
    result: EvaluateResult


class EvaluateErrorResponse(ApiResponse):
    result: None = None


@router.post(
    "/evaluate",
    response_model=EvaluateResponse,
    responses={404: {"model": EvaluateErrorResponse}, 409: {"model": EvaluateErrorResponse}},
)
async def evaluate_analysis(request: EvaluateRequest) -> EvaluateResponse | JSONResponse:
    # session_detail은 gate와 독립적인 조회라 병렬로 같이 보낸다 — 세션 없음(404)은
    # 둘 다 같은 테이블을 보므로 어느 쪽에서 걸려도 동일하다.
    session_detail, gate = await asyncio.gather(
        get_analysis_session_detail(request.session_id),
        judge_gate(GateRequest(session_id=request.session_id)),
    )
    if isinstance(session_detail, JSONResponse):
        return session_detail
    if isinstance(gate, JSONResponse):
        return gate

    service_type = session_detail.result.service_type

    if gate.verdict == "FAIL":
        results = await asyncio.gather(
            judge_regulatory_risk(GateRequest(session_id=request.session_id)),
            judge_correction_candidates(GateRequest(session_id=request.session_id)),
            _find_section_links(gate, service_type),
        )
        for response in results:
            if isinstance(response, JSONResponse):
                return response
        regulatory_risk, correction_candidates, section_links = results
        data_feasibility = market_feasibility = business_model = None
    else:
        results = await asyncio.gather(
            judge_regulatory_risk(GateRequest(session_id=request.session_id)),
            judge_correction_candidates(GateRequest(session_id=request.session_id)),
            assess_data_feasibility(FeasibilityRequest(session_id=request.session_id)),
            assess_market_feasibility(MarketFeasibilityRequest(session_id=request.session_id)),
            recommend_business_model(BusinessModelRequest(session_id=request.session_id)),
            _find_section_links(gate, service_type),
        )
        for response in results:
            if isinstance(response, JSONResponse):
                return response
        (
            regulatory_risk,
            correction_candidates,
            data_feasibility_response,
            market_feasibility_response,
            business_model_response,
            section_links,
        ) = results
        data_feasibility = data_feasibility_response.result
        market_feasibility = market_feasibility_response.result
        business_model = business_model_response.result

    return EvaluateResponse(
        isSuccess=True,
        code="ANALYSIS_EVALUATED",
        message="통합 판정이 완료되었습니다.",
        result=EvaluateResult(
            session=session_detail.result,
            gate=gate,
            regulatory_risk=regulatory_risk,
            correction_candidates=correction_candidates,
            data_feasibility=data_feasibility,
            market_feasibility=market_feasibility,
            business_model=business_model,
            section_links=section_links,
        ),
    )
