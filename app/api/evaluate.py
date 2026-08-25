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
from typing import Literal

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
from app.domain.report_llm import (
    LLMUnavailable,
    generate_bm_card_strengths,
    generate_differentiation_point,
    generate_one_liner,
    generate_overall_summary,
)
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


OverallSignal = Literal["빨강", "노랑", "초록"]


def _compute_overall_signal(
    gate: GateResponse,
    regulatory_risk: RegulatoryRiskResponse,
    data_feasibility: DataFeasibilityResult | None,
    market_feasibility: MarketFeasibilityResult | None,
    business_model: BusinessModelResult | None,
) -> OverallSignal:
    """SECTION 0 종합 신호등 (판정엔진_개발설계서.md §11). 순수 규칙 기반 — LLM 관여 없음
    ("LLM 불가침 값 고정" 원칙, §12).

    GATE FAIL이면 규제위험도만으로 판정한다(§11.2) — data_feasibility/market_feasibility/
    business_model이 전부 None인 상태라 초록 조건(넷 다 필요) 자체가 성립 불가능하므로
    별도 분기 없이 아래 일반 로직을 그대로 태워도 같은 결과가 나온다: 규제위험도
    높음이면 빨강, 아니면(None 체크로 초록 조건이 항상 거짓이 되어) 노랑.
    """
    if regulatory_risk.regulatory_grade == "높음":
        return "빨강"
    if data_feasibility is not None and data_feasibility.risk_level == "HIGH":
        return "빨강"

    bm_exists = business_model is not None and business_model.match_level != "insufficient_data"
    if (
        regulatory_risk.regulatory_grade == "낮음"
        and data_feasibility is not None
        and data_feasibility.risk_level in ("LOW", "MEDIUM")
        and market_feasibility is not None
        and market_feasibility.market_realism_grade == "높음"
        and bm_exists
    ):
        return "초록"

    return "노랑"


def _build_report_context(
    *,
    session_service_name: str,
    gate: GateResponse,
    regulatory_risk: RegulatoryRiskResponse,
    correction_candidates: CorrectionCandidatesResponse,
    data_feasibility: DataFeasibilityResult | None,
    market_feasibility: MarketFeasibilityResult | None,
    business_model: BusinessModelResult | None,
    overall_signal: OverallSignal,
    differentiation_point: str | None,
    bm_card_summaries: list[BmCardSummary],
) -> str:
    """LLM④⑤(2단계) 프롬프트에 주입할 컨텍스트 — 1단계(①②③) 결과까지 전부 담는다
    (§12 관리 원칙 "호출 간 모순 방지"). 판정 필드(등급·점수·verdict·overall_signal)는
    여기서 텍스트로만 노출되고, generate_overall_summary/generate_one_liner의 출력
    스키마엔 안 들어가 있어 LLM이 이 값을 구조적으로 바꿀 수 없다."""
    lines = [
        f"서비스명: {session_service_name}",
        f"종합 신호등: {overall_signal}",
        f"GATE 판정: {gate.verdict} ({gate.data_type}/{gate.function_type})",
    ]
    if gate.reasoning:
        lines.append("GATE 판정 근거: " + " ".join(gate.reasoning))
    if gate.verdict == "FAIL" and (gate.avoidance_redesign or gate.avoidance_certification):
        lines.append(
            f"GATE FAIL 회피 방향: 재설계 - {gate.avoidance_redesign or '없음'} / "
            f"인증 - {gate.avoidance_certification or '없음'}"
        )
    lines.append(
        f"규제 위험도: {regulatory_risk.regulatory_grade}"
        f"(의료행위표현 {regulatory_risk.regulatory_score}, 개인정보 {regulatory_risk.privacy_grade},"
        f" 광고표현 {regulatory_risk.advertising_grade})"
    )
    if regulatory_risk.applicable_laws:
        lines.append("적용 법령: " + ", ".join(regulatory_risk.applicable_laws))
    if correction_candidates.candidates:
        lines.append(f"위험 표현 교정 후보 {len(correction_candidates.candidates)}건 발견")

    if data_feasibility is not None:
        lines.append(f"데이터 확보 가능성: {data_feasibility.risk_level}")
    if market_feasibility is not None:
        lines.append(
            f"시장 현실성: {market_feasibility.market_realism_grade}"
            f"(경쟁사 {market_feasibility.competitor_count}개, 국내수요 {market_feasibility.domestic_demand or '미확인'})"
        )
    if business_model is not None and business_model.recommendations:
        bm_names = ", ".join(r.bm_pattern for r in business_model.recommendations if r.bm_pattern)
        lines.append(f"추천 BM: {bm_names or '검증 필요'}")
    if differentiation_point:
        lines.append(f"차별화 포인트: {differentiation_point}")
    for summary in bm_card_summaries:
        if summary.strength:
            lines.append(f"BM({summary.bm_pattern}) 강점: {summary.strength}")

    return "\n".join(lines)


_AI_STAGE_TIMEOUT_SECONDS = 20.0


async def _run_llm_stage1(
    service_description: str,
    market_feasibility: MarketFeasibilityResult | None,
    business_model: BusinessModelResult | None,
) -> tuple[str | None, list[BmCardSummary]]:
    """LLM②③ 병렬 — §12 1단계. 스테이지 전체에 상한을 둬서(D-16, 코드 리뷰 논의
    2026-08-25) 개별 호출이 오래 걸려도 /evaluate가 무한정 늘어지지 않게 한다.
    시간 초과면 둘 다 None/빈 값 — 이미 nullable이라 기존 폴백 패턴 그대로 이어진다."""
    try:
        return await asyncio.wait_for(
            asyncio.gather(
                _find_differentiation_point(service_description, market_feasibility),
                _build_bm_card_summaries(service_description, business_model),
            ),
            timeout=_AI_STAGE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return None, []


async def _run_llm_stage2(report_context: str) -> tuple[str | None, str | None]:
    """LLM④⑤ 병렬 — §12 2단계(1단계 뒤에 순차로 오되, ④⑤끼리는 병렬 —
    "총 지연 = max(①②③) + max(④⑤)"). 마찬가지로 스테이지 전체에 상한을 둔다."""

    async def _summary() -> str | None:
        try:
            return await generate_overall_summary(report_context)
        except LLMUnavailable:
            return None

    async def _one_liner() -> str | None:
        try:
            return await generate_one_liner(report_context)
        except LLMUnavailable:
            return None

    try:
        return await asyncio.wait_for(
            asyncio.gather(_summary(), _one_liner()), timeout=_AI_STAGE_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        return None, None


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
    # 종합 신호등(§11) — 순수 규칙 기반, LLM이 못 바꾼다. GATE FAIL이어도 항상 계산됨(§5.4).
    overall_signal: OverallSignal
    # LLM④⑤(§12 2단계) — 마찬가지로 LLM 미가용/타임아웃이면 None.
    overall_summary: str | None
    one_liner: str | None


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
        # overall_actions(DB/규칙 기반, §13 SECTION 3 액션)와 LLM②③ 스테이지(§12 1단계,
        # 외부 API)는 서로 의존성이 없어 한 번에 묶는다 — LLM②③ 자체는 _run_llm_stage1
        # 안에서 wait_for로 상한을 두므로(D-16 논의), overall_actions는 그 상한과 무관하게
        # 항상 빠르게 끝난다.
        overall_actions, stage1_result = await asyncio.gather(
            _find_overall_actions(data_feasibility, market_feasibility),
            _run_llm_stage1(service_description, market_feasibility, business_model),
        )
        differentiation_point, bm_card_summaries = stage1_result

    # §11 종합 신호등 — GATE FAIL이면 data_feasibility/market_feasibility/business_model이
    # 전부 None이라 초록 조건이 성립 불가능해서 별도 분기 없이도 §11.2와 같은 결과가 나온다.
    overall_signal = _compute_overall_signal(
        gate, regulatory_risk, data_feasibility, market_feasibility, business_model
    )
    # §12 2단계(LLM④⑤) — 1단계(①②③) 결과까지 전부 주입해 섹션 간 모순을 막는다.
    # GATE FAIL이어도 SECTION 3/0은 계속 만들어진다(§5.4 "리포트를 종료하지 않는다").
    report_context = _build_report_context(
        session_service_name=session_detail.result.service_name,
        gate=gate,
        regulatory_risk=regulatory_risk,
        correction_candidates=correction_candidates,
        data_feasibility=data_feasibility,
        market_feasibility=market_feasibility,
        business_model=business_model,
        overall_signal=overall_signal,
        differentiation_point=differentiation_point,
        bm_card_summaries=bm_card_summaries,
    )
    overall_summary, one_liner = await _run_llm_stage2(report_context)

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
            overall_signal=overall_signal,
            overall_summary=overall_summary,
            one_liner=one_liner,
        ),
    )
