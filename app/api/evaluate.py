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
from sqlalchemy import desc, or_, select

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
from app.db.models import ActionTemplate, Competitor, SectionLinkRule
from app.db.session import AsyncSessionLocal
from app.domain.report_llm import LLMUnavailable, generate_bm_card_strengths, generate_differentiation_point
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


class NextAction(BaseModel):
    action_text: str
    ref_doc: str | None
    priority: int


_NEXT_ACTIONS_LIMIT = 4


class OverallAction(BaseModel):
    action_text: str
    ref_doc: str | None
    tag: str
    priority: int


_OVERALL_ACTIONS_LIMIT_PER_TAG = 4
_OVERALL_ACTION_TAGS = ("[지금 당장]", "[출시 전 필수]")
# data_feasibility.risk_level(영문, feasibility.py)과 action_templates.trigger_value(국문,
# DB 실측 확인)가 서로 다른 표기라 매핑이 필요하다 — db_구축_설계서.md §3.4 등급과 동일한
# 대응(쉬움/보통/어려움).
_DATA_LEVEL_TO_KOREAN = {"LOW": "쉬움", "MEDIUM": "보통", "HIGH": "어려움"}


async def _find_overall_actions(
    data_feasibility: DataFeasibilityResult | None,
    market_feasibility: MarketFeasibilityResult | None,
) -> list[OverallAction]:
    """action_templates(scope=OVERALL) 조회 — SECTION 3 "[지금 당장]/[출시 전 필수]"
    (판정엔진_개발설계서.md §13 SECTION 3, §15.3). GATE FAIL이면 data_feasibility/
    market_feasibility가 None이라(§5.4) trigger_type=공통(무관)만 매칭된다.
    tag별로 상위 4개까지만 노출 — §15.3 "조합 폭발 방지 — 단일 조건 트리거 +
    priority 상위 3~4개만 노출" 원칙을 SECTION 조회(_find_next_actions)와 동일하게 적용.
    """
    conditions = [(ActionTemplate.trigger_type == "공통") & (ActionTemplate.trigger_value == "무관")]
    if data_feasibility is not None:
        data_level = _DATA_LEVEL_TO_KOREAN[data_feasibility.risk_level]
        conditions.append(
            (ActionTemplate.trigger_type == "data_level") & (ActionTemplate.trigger_value == data_level)
        )
    if market_feasibility is not None and market_feasibility.market_realism_grade is not None:
        conditions.append(
            (ActionTemplate.trigger_type == "market_level")
            & (ActionTemplate.trigger_value == market_feasibility.market_realism_grade)
        )

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(ActionTemplate)
                .where(ActionTemplate.scope == "OVERALL", or_(*conditions))
                .order_by(desc(ActionTemplate.priority))
            )
        ).scalars().all()

    grouped: dict[str, list[OverallAction]] = {tag: [] for tag in _OVERALL_ACTION_TAGS}
    for row in rows:
        bucket = grouped.get(row.tag or "")
        if bucket is None or len(bucket) >= _OVERALL_ACTIONS_LIMIT_PER_TAG:
            continue
        bucket.append(OverallAction(action_text=row.action_text, ref_doc=row.ref_doc, tag=row.tag, priority=row.priority))

    return [action for tag in _OVERALL_ACTION_TAGS for action in grouped[tag]]


async def _find_differentiation_point(
    service_description: str, market_feasibility: MarketFeasibilityResult | None
) -> str | None:
    """SECTION 2-3 "차별화 포인트"(판정엔진_개발설계서.md §12 LLM②). GATE FAIL이면
    market_feasibility가 None이라(§5.4) 호출하지 않는다. LLM 미가용(키 없음·호출
    실패)이면 None — 리포트 나머지는 계속 만들어진다."""
    if market_feasibility is None:
        return None
    try:
        return await generate_differentiation_point(
            service_description, [c.model_dump() for c in market_feasibility.competitor_cards]
        )
    except LLMUnavailable:
        return None


class BmCardSummary(BaseModel):
    bm_pattern: str | None
    frequency_score: int | None
    precedent_level: str | None
    price: str | None
    strength: str | None


async def _find_competitor_prices(competitor_names: set[str]) -> dict[str, str]:
    """competitors.name은 PK가 아니라 동명 행이 여러 개 있을 수 있다(예: "삼성헬스"가
    서로 다른 competitor_id로 3건 — 코드 리뷰로 확인, 2026-08-25). 이름 기준 dict
    컴프리헨션으로 그냥 덮어쓰면 어느 행이 남을지 쿼리 순서에 좌우돼 비결정적이므로,
    competitor_id로 정렬해 항상 같은 행이 이기게 고정한다."""
    if not competitor_names:
        return {}
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(Competitor.name, Competitor.price)
                .where(Competitor.name.in_(competitor_names))
                .order_by(Competitor.competitor_id)
            )
        ).all()
    prices: dict[str, str] = {}
    for name, price in rows:
        if price and name not in prices:
            prices[name] = price
    return prices


async def _build_bm_card_summaries(
    service_description: str, business_model: BusinessModelResult | None
) -> list[BmCardSummary]:
    """SECTION 2-4 "BM 카드 4줄 요약"(판정엔진_개발설계서.md §9.3, §12 LLM③).

    가격대는 competitors.price DB 조회(LLM 아님), 강점은 LLM③ 생성. 전환율은
    §9.3이 "수집 가능성 미확인"으로 명시한 축이라 이 응답에 포함하지 않는다 —
    없는 데이터를 임의로 만들어내지 않는다."""
    if business_model is None or not business_model.recommendations:
        return []

    all_names: set[str] = set()
    for rec in business_model.recommendations:
        if rec.contributing_competitor_ids:
            all_names.update(name.strip() for name in rec.contributing_competitor_ids.split(","))
    prices = await _find_competitor_prices(all_names)

    try:
        strengths = await generate_bm_card_strengths(
            service_description,
            [
                {"bm_pattern": rec.bm_pattern, "contributing_competitor_ids": rec.contributing_competitor_ids}
                for rec in business_model.recommendations
            ],
        )
    except LLMUnavailable:
        strengths = {}

    summaries = []
    for rec in business_model.recommendations:
        names = [name.strip() for name in (rec.contributing_competitor_ids or "").split(",") if name.strip()]
        price = next((prices[name] for name in names if name in prices), None)
        summaries.append(
            BmCardSummary(
                bm_pattern=rec.bm_pattern,
                frequency_score=rec.frequency_score,
                precedent_level=rec.precedent_level,
                price=price,
                strength=strengths.get(rec.bm_pattern) if rec.bm_pattern else None,
            )
        )
    return summaries


async def _find_next_actions(gate: GateResponse, regulatory_risk: RegulatoryRiskResponse) -> list[NextAction]:
    """action_templates(scope=SECTION) 조회 — SECTION 2-1·부록 "다음 액션 3~4개"
    (판정엔진_개발설계서.md §15.3). gate_verdict는 judge_gate, risk_level/sensitivity_level은
    judge_regulatory_risk 결과가 있어야 나와서 두 서브 호출이 끝난 뒤에만 조회 가능하다.
    priority 상위 §15.3 기준대로 4개까지만 노출 — 조합 폭발 방지."""
    conditions = [
        (ActionTemplate.trigger_type == "gate_verdict") & (ActionTemplate.trigger_value == gate.verdict),
        (ActionTemplate.trigger_type == "risk_level")
        & (ActionTemplate.trigger_value == regulatory_risk.regulatory_grade),
        (ActionTemplate.trigger_type == "sensitivity_level")
        & (ActionTemplate.trigger_value == str(regulatory_risk.privacy_score)),
    ]
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(ActionTemplate)
                .where(ActionTemplate.scope == "SECTION", or_(*conditions))
                .order_by(desc(ActionTemplate.priority))
                .limit(_NEXT_ACTIONS_LIMIT)
            )
        ).scalars().all()
    return [NextAction(action_text=row.action_text, ref_doc=row.ref_doc, priority=row.priority) for row in rows]


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
    next_actions: list[NextAction]
    overall_actions: list[OverallAction]
    # LLM 미가용(OPENAI_API_KEY 없음·호출 실패)이면 None/빈 리스트 — §12 LLM②③.
    differentiation_point: str | None
    bm_card_summaries: list[BmCardSummary]


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
        next_actions = await _find_next_actions(gate, regulatory_risk)
        data_feasibility = market_feasibility = business_model = None
        overall_actions = await _find_overall_actions(data_feasibility, market_feasibility)
        differentiation_point = None
        bm_card_summaries: list[BmCardSummary] = []
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
        next_actions = await _find_next_actions(gate, regulatory_risk)
        data_feasibility = data_feasibility_response.result
        market_feasibility = market_feasibility_response.result
        business_model = business_model_response.result
        service_description = session_detail.result.service_description
        # 셋 다 서로 의존성이 없어 한 번에 묶는다 — 순서대로 await하면 DB
        # 왕복(overall_actions)만큼 LLM 호출(differentiation_point/bm_card_summaries)
        # 뒤로 지연이 더해진다(코드 리뷰로 확인된 개선점, 2026-08-25).
        overall_actions, differentiation_point, bm_card_summaries = await asyncio.gather(
            _find_overall_actions(data_feasibility, market_feasibility),
            _find_differentiation_point(service_description, market_feasibility),
            _build_bm_card_summaries(service_description, business_model),
        )

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
            next_actions=next_actions,
            overall_actions=overall_actions,
            differentiation_point=differentiation_point,
            bm_card_summaries=bm_card_summaries,
        ),
    )
