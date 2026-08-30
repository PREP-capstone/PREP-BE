"""판정 API — 1번 담당(Gate/규제 위험도 판정). 이슈 1: judgement/gate.

data_type/function_type/acquire_method/invasive_signal 판별은 규칙 기반이다(LLM 미사용).
health_data_items[].data_type은 값 타입(numeric/text/image 등)이고 GATE_MATRIX_TABLE의
data_type(라이프스타일/생체지표)과는 이름만 같고 뜻이 다르다.
"""

import asyncio
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.api.rag import RagChunkLookupRequest, lookup_rag_chunks
from app.db.models import (
    AnalysisSession,
    CorrectionRule,
    DataSensitivity,
    GateKeyword,
    HealthDataItem,
    ServiceLawMap,
    SignalConfig,
)
from app.db.rule_version_queries import resolve_active_rule_version_ids
from app.db.session import AsyncSessionLocal
from app.domain.correction_llm import generate_correction_candidates
from app.domain.health_data import SOURCE_TO_ACQUIRE_METHOD, is_biomarker_name, load_biomarker_keywords
from app.domain.legal_documents import DOCUMENT_TITLES
from app.domain.scoring import grade_by_threshold
from app.pipeline.correction_terms import keyword_score
from app.pipeline.gate_matrix_table import (
    GATE_MATRIX_TABLE,
    HARDCHECK_AVOIDANCE_CERTIFICATION,
    HARDCHECK_AVOIDANCE_REDESIGN,
    HARDCHECK_VERDICT,
    detect_invasive,
    is_invasive_hardcheck,
)
from app.schemas.common import ApiResponse, HealthDataItemInput, LegalBasis

router = APIRouter(prefix="/api/v1/judgement", tags=["judgement"])


class JudgementErrorResponse(ApiResponse):
    result: None = None


def _session_not_found_response() -> JSONResponse:
    # feasibility.py(이슈 #38)와 같은 코드/메시지 — 세션 조회 실패는 두 API에서 같은 모양이어야
    # 프론트가 에러 처리를 하나로 통일할 수 있다.
    return JSONResponse(
        status_code=404,
        content=JudgementErrorResponse(
            isSuccess=False,
            code="ANALYSIS_SESSION_NOT_FOUND",
            message="분석 세션을 찾을 수 없습니다.",
        ).model_dump(),
    )


def _no_health_data_response() -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content=JudgementErrorResponse(
            isSuccess=False,
            code="HEALTH_DATA_REQUIRED",
            message="등록된 검진 데이터가 없습니다. 먼저 health-data를 등록해주세요.",
        ).model_dump(),
    )


async def _load_session(session_id: str) -> tuple[AnalysisSession, list[HealthDataItemInput]] | JSONResponse:
    """session_id로 analysis_sessions/health_data_items를 조회해 judgement 로직이 쓰는
    HealthDataItemInput 목록으로 변환한다. feasibility.py(이슈 #38)와 같은 조회 패턴 —
    별도 세션 조회 API를 HTTP로 호출하지 않고 같은 프로세스에서 직접 쿼리한다.

    health_data_items가 비어도 그대로 반환한다(404만 여기서 처리) — correction-candidates는
    항목을 아예 안 쓰므로 "검진 데이터 필요" 체크는 실제로 쓰는 엔드포인트가 각자 판단한다.
    """
    async with AsyncSessionLocal() as session:
        analysis_session = await session.get(AnalysisSession, session_id)
        if analysis_session is None:
            return _session_not_found_response()
        rows = (
            await session.execute(
                select(HealthDataItem)
                .where(HealthDataItem.session_id == session_id)
                .order_by(HealthDataItem.sort_order, HealthDataItem.created_at)
            )
        ).scalars().all()

    items = [
        HealthDataItemInput(
            name=row.name,
            data_type=row.data_type,
            unit=row.unit,
            source=row.source,
            is_sensitive=row.is_sensitive,
            item_code=row.item_code,
        )
        for row in rows
    ]
    return analysis_session, items


# 룰베이스_RAG_정합성_추적표.md 표1에서 ✅(정상/해소)로 확인된 문서만. document_id가 우연히
# 일치해도 판본이 다르거나(비의료 건강관리서비스 가이드라인) 미청킹인 문서는 quote를 채우면
# 틀린 원문이 나올 수 있어 제외한다 — 그 표가 갱신되면 이 목록도 같이 갱신해야 한다.
_RAG_TRUSTED_DOCUMENT_IDS = {
    "kr-mfds-wellness-0091-03-20260212",
    "kr-pharmaceutical-affairs-act-20260621",
    "kr-medical-device-act-20260701",
    "kr-medical-device-act-rule-annex7-20260701",
    "kr-medical-act-20260407",
}


class GateRequest(BaseModel):
    session_id: str


class GateResponse(BaseModel):
    data_type: str
    function_type: str
    acquire_method: str | None
    invasive_signal: bool
    verdict: str
    hardcheck_fired: bool
    # GATE FAIL일 때 회피 방향 2가지(D-2, 코드 템플릿 방식). PASS/CONDITIONAL이면 둘 다 None.
    avoidance_redesign: str | None
    avoidance_certification: str | None
    reasoning: list[str]


# 여러 액션이 섞이면 가장 위험한 쪽 채택 (db_구축_설계서.md §3.2 "복수 조합 시 FAIL 우선").
_ACTION_PRIORITY: list[tuple[set[str], str]] = [
    ({"predict", "diagnose", "alert"}, "수치예측·진단"),
    ({"visualize_trend"}, "비교·추이분석"),
    ({"record"}, "단순기록"),
]

# 기기연동이어야 침습적 하드체크가 발동하므로 최우선. 기관연동(기관 데이터 연계, collection_difficulty
# S축 최고값=10)은 하드체크와 무관하지만 수동입력/OS연동보다 눈에 띄어야 하는 획득방법이라 그다음 순위.
_ACQUIRE_METHOD_PRIORITY = ("기기연동", "기관연동", "OS연동", "수동입력")


def _classify_data_type(items: list[HealthDataItemInput], biomarker_keywords: set[str]) -> str:
    for item in items:
        if is_biomarker_name(item.name, biomarker_keywords):
            return "생체지표"
    return "라이프스타일"


def _classify_function_type(actions: list[str]) -> str:
    action_set = set(actions)
    for trigger_actions, function_type in _ACTION_PRIORITY:
        if action_set & trigger_actions:
            return function_type
    return "단순기록"


def _classify_acquire_method(items: list[HealthDataItemInput]) -> str | None:
    methods = {SOURCE_TO_ACQUIRE_METHOD.get(item.source) for item in items}
    for method in _ACQUIRE_METHOD_PRIORITY:
        if method in methods:
            return method
    return None


_FUNCTION_TYPE_DESCRIPTIONS = {
    "단순기록": "기능은 단순 기록·조회 수준에 머물러 있어 비교·추이분석이나 수치예측·진단 기능은 포함되지 않습니다.",
    "비교·추이분석": "기능은 비교·추이분석 수준으로, 수치를 비교·해석해 보여주지만 예측·진단까지는 하지 않습니다.",
}


def _describe_function_type(data_type: str, function_type: str) -> str:
    # "수치예측·진단"은 data_type에 따라 GATE_MATRIX_TABLE의 verdict가 갈린다
    # (생체지표=FAIL, 라이프스타일=CONDITIONAL) — 문구도 그에 맞춰 갈라야 한다.
    if function_type == "수치예측·진단":
        if data_type == "생체지표":
            return "기능이 수치예측·진단 수준까지 포함돼 의료기기 해당 가능성이 가장 높은 조합입니다."
        return "기능이 수치예측·진단 수준까지 포함되지만, 라이프스타일 데이터라 조건부 통과(CONDITIONAL) 수준의 조합입니다."
    return _FUNCTION_TYPE_DESCRIPTIONS[function_type]


def _describe_data_and_acquire(
    data_type: str, acquire_method: str | None, invasive_signal: bool, hardcheck_fired: bool
) -> str:
    if hardcheck_fired:
        # data_type/acquire_method는 각각 다른 데이터 항목에서 나왔을 수 있다(_classify_data_type은
        # 생체지표 항목 하나만 있어도, _classify_acquire_method는 전체 항목 중 우선순위가 가장 높은
        # 수집방법을 고른다) — "이 조합"처럼 동일 항목을 암시하지 않도록 문구를 분리해서 서술한다.
        return f"등록된 항목 중 {data_type}에 해당하는 항목이 있고, 전체 항목 기준 수집방법이 {acquire_method}으로 분류되어 침습적 하드체크 대상입니다."
    if data_type == "생체지표" and acquire_method == "기기연동":
        # hardcheck_fired=False인데 여기 도달했다는 건 invasive_signal=False였다는 뜻
        # (is_invasive_hardcheck는 생체지표+기기연동+invasive_signal 셋 다 True일 때만 발동).
        return "생체지표 데이터를 기기연동으로 수집하지만 침습적 신호는 감지되지 않아 하드체크 대상이 아닙니다."
    if data_type == "생체지표":
        return f"생체지표 데이터를 다루지만 수집 방법이 기기연동이 아닌 {acquire_method}이라 침습적 하드체크 대상이 아닙니다."
    if invasive_signal:
        # data_type=="라이프스타일"이면 is_invasive_hardcheck가 절대 발동하지 않는다 — 침습 신호가
        # 있어도 왜 하드체크로 안 이어지는지 명시해야 reasoning[2](침습 신호 감지)와 모순돼 보이지 않는다.
        return f"{data_type} 데이터를 {acquire_method}으로 수집하며, 침습적 신호가 감지됐지만 생체지표가 아니라 하드체크 대상이 아닙니다."
    return f"{data_type} 데이터를 {acquire_method}으로 수집합니다."


def _describe_invasive_signal(invasive_signal: bool) -> str:
    if invasive_signal:
        return "서비스 설명·데이터 항목명에서 침습적 신호가 감지됐습니다."
    return "서비스 설명·데이터 항목명 어디에서도 침습적 신호가 감지되지 않았습니다."


def _describe_verdict(verdict: str | None, hardcheck_fired: bool) -> str:
    if hardcheck_fired:
        return "생체지표·기기연동·침습적 신호가 모두 겹쳐 하드체크로 FAIL 판정됐습니다."
    if verdict == "PASS":
        return "위 조합은 GATE 매트릭스 기준 의료기기 해당 가능성이 낮은 조합으로 판정됐습니다(PASS)."
    if verdict == "CONDITIONAL":
        return "위 조합은 GATE 매트릭스 기준 조건부 통과(CONDITIONAL)로 판정됐습니다 — 추가 검토가 필요합니다."
    return "위 조합은 GATE 매트릭스 기준 의료기기 해당 가능성이 높은 조합으로 판정됐습니다(FAIL)."


def _build_gate_reasoning(
    data_type: str,
    function_type: str,
    acquire_method: str | None,
    invasive_signal: bool,
    hardcheck_fired: bool,
    verdict: str | None = None,
) -> list[str]:
    # 하드체크가 곧 FAIL을 뜻하므로 호출부가 verdict="FAIL"을 손으로 맞춰줄 필요 없이
    # 여기서 HARDCHECK_VERDICT를 직접 쓴다 — 매트릭스 경로만 cell의 verdict를 그대로 받는다.
    resolved_verdict = HARDCHECK_VERDICT if hardcheck_fired else verdict
    return [
        _describe_data_and_acquire(data_type, acquire_method, invasive_signal, hardcheck_fired),
        _describe_function_type(data_type, function_type),
        _describe_invasive_signal(invasive_signal),
        _describe_verdict(resolved_verdict, hardcheck_fired),
    ]


def _detect_invasive_signal(service_description: str, items: list[HealthDataItemInput]) -> bool:
    # detect_invasive()는 내부에서 공백을 전부 지우고 매칭한다 — 서로 다른 필드를
    # 이어붙이면 경계가 사라져 부정표현/키워드가 필드를 가로질러 엉뚱하게 매칭된다.
    # 그래서 필드별로 따로 검사해 OR로 합친다.
    texts = [service_description] + [item.name for item in items]
    return any(detect_invasive(text) for text in texts)


@router.post(
    "/gate",
    response_model=GateResponse,
    responses={404: {"model": JudgementErrorResponse}, 409: {"model": JudgementErrorResponse}},
)
async def judge_gate(request: GateRequest) -> GateResponse | JSONResponse:
    loaded = await _load_session(request.session_id)
    if isinstance(loaded, JSONResponse):
        return loaded
    analysis_session, health_data_items = loaded
    if not health_data_items:
        return _no_health_data_response()

    async with AsyncSessionLocal() as session:
        biomarker_keywords = await load_biomarker_keywords(session)
    data_type = _classify_data_type(health_data_items, biomarker_keywords)
    function_type = _classify_function_type(analysis_session.service_actions)
    acquire_method = _classify_acquire_method(health_data_items)
    invasive_signal = _detect_invasive_signal(analysis_session.service_description, health_data_items)

    if is_invasive_hardcheck(data_type, acquire_method, invasive_signal):
        return GateResponse(
            data_type=data_type,
            function_type=function_type,
            acquire_method=acquire_method,
            invasive_signal=invasive_signal,
            verdict="FAIL",
            hardcheck_fired=True,
            avoidance_redesign=HARDCHECK_AVOIDANCE_REDESIGN,
            avoidance_certification=HARDCHECK_AVOIDANCE_CERTIFICATION,
            reasoning=_build_gate_reasoning(
                data_type, function_type, acquire_method, invasive_signal, hardcheck_fired=True
            ),
        )

    cell = GATE_MATRIX_TABLE[(data_type, function_type)]
    return GateResponse(
        data_type=data_type,
        function_type=function_type,
        acquire_method=acquire_method,
        invasive_signal=invasive_signal,
        verdict=cell["verdict"],
        hardcheck_fired=False,
        avoidance_redesign=cell.get("avoidance_redesign"),
        avoidance_certification=cell.get("avoidance_certification"),
        reasoning=_build_gate_reasoning(
            data_type, function_type, acquire_method, invasive_signal, hardcheck_fired=False, verdict=cell["verdict"]
        ),
    )


# ---- judgement/regulatory-risk ----

_AXIS_TO_SCORE_FIELD = {
    "의료행위표현": "regulatory_score",
    "개인정보민감도": "privacy_score",
    "광고표현위험": "advertising_score",
}


class MatchedRule(BaseModel):
    legal_basis: LegalBasis
    exact_phrase_match: bool


class RegulatoryRiskResponse(BaseModel):
    regulatory_score: int
    regulatory_grade: str
    privacy_score: int
    privacy_grade: str
    advertising_score: int
    advertising_grade: str
    matched_rules: list[MatchedRule]
    # 판단근거③(서비스 형태 기반 적용 법령) — service_type 미입력이거나 매칭 없으면 빈 값.
    applicable_laws: list[str]
    service_law_description: str | None


def _grade(score: int, threshold_low: int, threshold_mid: int) -> str:
    return grade_by_threshold(score, threshold_low, threshold_mid, ("낮음", "중간", "높음"))


async def _signal_thresholds(rule_version_ids: list[uuid.UUID]) -> dict[str, tuple[int, int]]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(SignalConfig).where(SignalConfig.rule_version_id.in_(rule_version_ids))
            )
        ).scalars().all()
    thresholds: dict[str, tuple[int, int]] = {}
    for row in rows:
        if row.axis in thresholds:
            raise HTTPException(
                status_code=500,
                detail=f"signal_config에 축 '{row.axis}'의 활성 임계값이 중복됩니다",
            )
        thresholds[row.axis] = (row.threshold_low, row.threshold_mid)
    return thresholds


class CorrectionMatch(BaseModel):
    risky_text: str
    safe_text: str
    regulatory_score: int
    advertising_score: int
    legal_basis: LegalBasis
    exact_phrase_match: bool
    # 규칙 기반(correction_rules) 매칭인지 LLM①(이슈 #58) 폴백 추정인지 (D-15). exact_phrase_match와
    # 달리 keyword_hit으로 매칭된 정상 규칙 기반 항목도 포함해 "규칙 vs LLM"을 명확히 구분한다.
    match_source: Literal["rule", "llm"]


async def _match_gate_keywords(service_description: str, rule_version_ids: list[uuid.UUID]) -> list[GateKeyword]:
    """gate_keywords를 단어 단위로 직접 매칭 — correction_rules.risky_text 문구 매칭보다 recall이 높다."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(GateKeyword).where(GateKeyword.rule_version_id.in_(rule_version_ids))
            )
        ).scalars().all()
    return [row for row in rows if row.keyword and row.keyword in service_description]


async def _fill_quotes(matches: list[CorrectionMatch]) -> None:
    """화이트리스트 문서에 한해 RAG에서 조문 원문을 조회해 legal_basis.quote를 채운다(in-place).

    RAG 조회가 실패해도 조용히 넘어간다 — RAG는 판정 결과를 절대 바꾸지 않는 부가 정보라서
    (판정엔진_개발설계서.md §10.1), RAG 장애로 핵심 응답까지 깨지면 안 된다.
    """
    by_document: dict[str, list[CorrectionMatch]] = {}
    for match in matches:
        if match.legal_basis.document_id in _RAG_TRUSTED_DOCUMENT_IDS:
            by_document.setdefault(match.legal_basis.document_id, []).append(match)

    for document_id, group in by_document.items():
        section_ids = list({m.legal_basis.article for m in group})
        try:
            response = await lookup_rag_chunks(
                RagChunkLookupRequest(document_id=document_id, section_ids=section_ids)
            )
        except Exception:
            continue
        chunk_by_section = {chunk.section_id: chunk.chunk_text for chunk in response.result}
        for match in group:
            match.legal_basis.quote = chunk_by_section.get(match.legal_basis.article)


async def _match_correction_rules(
    service_description: str, matched_keywords: list[GateKeyword], rule_version_ids: list[uuid.UUID]
) -> list[CorrectionMatch]:
    """correction_rules를 두 경로로 매칭해 합친다(rule_id 기준 중복 제거).

    ① risky_text 문구 포함 ② derived_from_keyword_id로 matched_keywords와 역참조 연결
    (원래 반대 방향 추적용 FK를 거꾸로 탄, 더 관대한 매칭).
    """
    matched_keyword_ids = {row.keyword_id for row in matched_keywords}

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(CorrectionRule).where(CorrectionRule.rule_version_id.in_(rule_version_ids))
            )
        ).scalars().all()

    matched: dict[str, CorrectionMatch] = {}
    for row in rows:
        phrase_hit = row.risky_text and row.risky_text in service_description
        keyword_hit = row.derived_from_keyword_id in matched_keyword_ids
        if not (phrase_hit or keyword_hit):
            continue
        matched[str(row.rule_id)] = CorrectionMatch(
            risky_text=row.risky_text,
            safe_text=row.safe_text,
            regulatory_score=row.regulatory_score,
            advertising_score=row.advertising_score,
            legal_basis=LegalBasis(
                document_id=row.legal_basis_doc,
                article=row.legal_basis_article,
                title=DOCUMENT_TITLES.get(row.legal_basis_doc),
            ),
            exact_phrase_match=bool(phrase_hit),
            match_source="rule",
        )
    result = list(matched.values())
    await _fill_quotes(result)
    return result


async def _match_correction_rules_with_llm_fallback(
    service_description: str, matched_keywords: list[GateKeyword], rule_version_ids: list[uuid.UUID]
) -> list[CorrectionMatch]:
    """규칙 기반(_match_correction_rules)이 0건일 때만 LLM①을 보완 호출한다(이슈 #58).

    2026-08-23 실측 — gate_keywords 68개 중 하나도 안 걸리는 파라프레이즈 표현(복약지도 등)은
    규칙 기반으로 원천적으로 못 잡는다. LLM 미가용(키 없음·호출 실패)이면 빈 리스트로
    조용히 폴백 — correction-candidates 응답 전체가 LLM 장애로 깨지면 안 된다(§10.1).
    """
    matches = await _match_correction_rules(service_description, matched_keywords, rule_version_ids)
    if matches:
        return matches

    try:
        raw_candidates = await generate_correction_candidates(service_description)
    except Exception:
        # LLMUnavailable(키 없음·호출 실패로 이 모듈이 직접 올리는 것)뿐 아니라 그 외 예기치
        # 못한 예외까지 전부 여기서 끊는다 — _fill_quotes()의 RAG 조회 실패 처리(위)와 같은
        # 이유: 이 호출은 보조 정보라 장애가 나도 judge_correction_candidates() 전체(나아가
        # evaluate.py의 asyncio.gather 안에서는 /evaluate 전체)를 절대 깨면 안 된다(§10.1).
        return []

    try:
        # (risky_text, document_id, article) 기준 중복 제거 — risky_text만 쓰면 같은 문구를
        # 서로 다른 법적 근거로 잡은 두 후보가 하나로 뭉개진다. 이 함수 자체가 LLM 장애 시
        # 빈 리스트로 조용히 폴백하는 게 계약이라, 여기서 KeyError가 나도(strict json_schema라
        # 사실상 안 나지만) 500 대신 빈 리스트로 빠져야 일관적이다.
        deduped: dict[tuple[str, str, str], dict] = {
            (item["risky_text"], item["legal_basis"]["document_id"], item["legal_basis"]["article"]): item
            for item in raw_candidates
        }
        llm_matches = [
            CorrectionMatch(
                risky_text=item["risky_text"],
                safe_text=item["safe_text"],
                # judge_correction_candidates()는 이 두 점수를 응답에 노출하지 않는다(CorrectionMatch를
                # 재사용하는 건 _fill_quotes() 그대로 태우기 위해서일 뿐) — 여기선 의미 없는 값.
                regulatory_score=0,
                advertising_score=0,
                legal_basis=LegalBasis(
                    document_id=item["legal_basis"]["document_id"],
                    article=item["legal_basis"]["article"],
                    title=DOCUMENT_TITLES.get(item["legal_basis"]["document_id"]),
                ),
                exact_phrase_match=False,
                match_source="llm",
            )
            for item in deduped.values()
        ]
    except (KeyError, TypeError):
        return []

    await _fill_quotes(llm_matches)
    return llm_matches


async def _find_service_law(service_type: str | None) -> ServiceLawMap | None:
    """service_law_map(§15.2)에서 service_type으로 직접 조회. service_type 없으면
    조회 자체를 건너뛴다 — category_1/category_2처럼 완화 단계가 없는 단일 PK 매칭."""
    if not service_type:
        return None
    async with AsyncSessionLocal() as session:
        return await session.get(ServiceLawMap, service_type)


async def _match_privacy_score(items: list[HealthDataItemInput]) -> int:
    """health_data_items[].item_code를 data_sensitivity.item_code(PK)와 직접 비교해 최댓값 채택.

    작업 #6 방향 B(2026-08-17 확정) — 문자열(item_label) 부분매칭은 표기가 조금만
    달라도 조용히 0점 처리되는 문제가 있어 폐기했다. 2번의 health-data API가
    item_code를 값으로 직접 보낸다.
    """
    item_codes = {item.item_code for item in items if item.item_code}
    if not item_codes:
        return 0

    async with AsyncSessionLocal() as session:
        levels = (
            await session.execute(
                select(DataSensitivity.sensitivity_level).where(DataSensitivity.item_code.in_(item_codes))
            )
        ).scalars().all()
    return max(levels, default=0)


@router.post(
    "/regulatory-risk",
    response_model=RegulatoryRiskResponse,
    responses={404: {"model": JudgementErrorResponse}, 409: {"model": JudgementErrorResponse}},
)
async def judge_regulatory_risk(request: GateRequest) -> RegulatoryRiskResponse | JSONResponse:
    loaded = await _load_session(request.session_id)
    if isinstance(loaded, JSONResponse):
        return loaded
    analysis_session, health_data_items = loaded
    if not health_data_items:
        return _no_health_data_response()

    # 활성 rule_version_id를 한 번만 확정해서 이후 모든 쿼리에 그대로 넘긴다 — 각 쿼리가
    # 따로 "활성"을 다시 판단하면 그 사이 publish()가 끼어들 때 스냅샷이 어긋날 수 있다.
    rule_version_ids = await resolve_active_rule_version_ids()

    # thresholds부터 먼저 확인한다 — signal_config에 축이 빠져 있으면 어차피 500인데,
    # gate_keywords/data_sensitivity 전체 스캔 같은 비싼 쿼리를 먼저 하고 버리지 않는다.
    thresholds = await _signal_thresholds(rule_version_ids)
    missing_axes = [axis for axis in _AXIS_TO_SCORE_FIELD if axis not in thresholds]
    if missing_axes:
        raise HTTPException(
            status_code=500,
            detail=f"signal_config에 활성 임계값이 없는 축: {missing_axes}",
        )

    # matches는 matched_keywords에 의존해 이후 실행, 나머지는 전부 독립적이라 병렬 조회.
    matched_keywords, privacy_score, service_law = await asyncio.gather(
        _match_gate_keywords(analysis_session.service_description, rule_version_ids),
        _match_privacy_score(health_data_items),
        _find_service_law(analysis_session.service_type),
    )
    matches = await _match_correction_rules(
        analysis_session.service_description, matched_keywords, rule_version_ids
    )
    # 키워드/문구 두 매칭 중 더 높은 점수 채택 — 한쪽이 놓친 걸 다른 쪽으로 보강.
    keyword_match_score = max((keyword_score(row) for row in matched_keywords), default=0)
    regulatory_score = max((m.regulatory_score for m in matches), default=0)
    regulatory_score = max(regulatory_score, keyword_match_score)
    advertising_score = max((m.advertising_score for m in matches), default=0)
    matched_rules = [
        MatchedRule(legal_basis=m.legal_basis, exact_phrase_match=m.exact_phrase_match) for m in matches
    ]

    scores = {
        "regulatory_score": regulatory_score,
        "privacy_score": privacy_score,
        "advertising_score": advertising_score,
    }
    grades: dict[str, str] = {}
    for axis, score_field in _AXIS_TO_SCORE_FIELD.items():
        low, mid = thresholds[axis]
        grades[score_field] = _grade(scores[score_field], low, mid)

    return RegulatoryRiskResponse(
        regulatory_score=regulatory_score,
        regulatory_grade=grades["regulatory_score"],
        privacy_score=privacy_score,
        privacy_grade=grades["privacy_score"],
        advertising_score=advertising_score,
        advertising_grade=grades["advertising_score"],
        matched_rules=matched_rules,
        applicable_laws=service_law.applicable_laws if service_law else [],
        service_law_description=service_law.description if service_law else None,
    )


# ---- judgement/correction-candidates ----


class CorrectionCandidate(BaseModel):
    risky_text: str
    safe_text: str
    legal_basis: LegalBasis
    exact_phrase_match: bool
    match_source: Literal["rule", "llm"]


class CorrectionCandidatesResponse(BaseModel):
    candidates: list[CorrectionCandidate]


@router.post(
    "/correction-candidates",
    response_model=CorrectionCandidatesResponse,
    responses={404: {"model": JudgementErrorResponse}, 409: {"model": JudgementErrorResponse}},
)
async def judge_correction_candidates(request: GateRequest) -> CorrectionCandidatesResponse | JSONResponse:
    loaded = await _load_session(request.session_id)
    if isinstance(loaded, JSONResponse):
        return loaded
    analysis_session, _health_data_items = loaded

    rule_version_ids = await resolve_active_rule_version_ids()
    matched_keywords = await _match_gate_keywords(analysis_session.service_description, rule_version_ids)
    matches = await _match_correction_rules_with_llm_fallback(
        analysis_session.service_description, matched_keywords, rule_version_ids
    )
    return CorrectionCandidatesResponse(
        candidates=[
            CorrectionCandidate(
                risky_text=m.risky_text,
                safe_text=m.safe_text,
                legal_basis=m.legal_basis,
                exact_phrase_match=m.exact_phrase_match,
                match_source=m.match_source,
            )
            for m in matches
        ]
    )
