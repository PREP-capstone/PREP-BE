"""통합 판정 오케스트레이션 API. gate 판정 결과로 나머지 5개 판정/추천 API를
조건부·병렬 호출해 하나의 응답으로 합친다 — 판정엔진_개발설계서.md §5.4 "GATE FAIL 분기".

session_id 하나만 받고 gate/regulatory-risk/correction-candidates/feasibility 2종/
business-model 전부 이 프로세스 안에서 함수로 직접 호출한다(HTTP 아님). category_1이
세션 생성 시 필수값이 됐으므로(app/api/analysis_sessions.py) 이 엔드포인트는 카테고리
분류를 호출하지 않는다 — 호출 시점엔 이미 확정돼 있다는 전제.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

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
    gate = await judge_gate(GateRequest(session_id=request.session_id))
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
            gate=gate,
            regulatory_risk=regulatory_risk,
            correction_candidates=correction_candidates,
            data_feasibility=data_feasibility,
            market_feasibility=market_feasibility,
            business_model=business_model,
        ),
    )
