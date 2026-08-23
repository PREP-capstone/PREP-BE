"""통합 판정 오케스트레이션 API. gate 판정 결과로 나머지 5개 판정/추천 API를
조건부·병렬 호출해 하나의 응답으로 합친다 — 판정엔진_개발설계서.md §5.4 "GATE FAIL 분기".

session_id 하나만 받고 세션 요약(get_analysis_session_detail)·gate·regulatory-risk·
correction-candidates·feasibility 2종·business-model 전부 이 프로세스 안에서 함수로
직접 호출한다(HTTP 아님). 카테고리 분류(category-classifier/predict)는 호출하지
않는다 — 프론트가 STEP1→2 전환 시 별도로 호출하고, PATCH .../category로 세션에
반영한 뒤에 evaluate를 부르는 흐름을 전제로 한다.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

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
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


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

    if gate.verdict == "FAIL":
        results = await asyncio.gather(
            judge_regulatory_risk(GateRequest(session_id=request.session_id)),
            judge_correction_candidates(GateRequest(session_id=request.session_id)),
        )
        for response in results:
            if isinstance(response, JSONResponse):
                return response
        regulatory_risk, correction_candidates = results
        data_feasibility = market_feasibility = business_model = None
    else:
        results = await asyncio.gather(
            judge_regulatory_risk(GateRequest(session_id=request.session_id)),
            judge_correction_candidates(GateRequest(session_id=request.session_id)),
            assess_data_feasibility(FeasibilityRequest(session_id=request.session_id)),
            assess_market_feasibility(MarketFeasibilityRequest(session_id=request.session_id)),
            recommend_business_model(BusinessModelRequest(session_id=request.session_id)),
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
        ),
    )
