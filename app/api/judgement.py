"""판정 API — 1번 담당(Gate/규제 위험도 판정). 이슈 1: judgement/gate.

data_type/function_type/acquire_method/invasive_signal 판별은 규칙 기반이다(LLM 미사용).
health_data_items[].data_type은 값 타입(numeric/text/image 등)이고 GATE_MATRIX_TABLE의
data_type(라이프스타일/생체지표)과는 이름만 같고 뜻이 다르다.
"""

import asyncio
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.db.models import CorrectionRule, DataSensitivity, SignalConfig
from app.db.rule_version_queries import resolve_active_rule_version_ids
from app.db.session import AsyncSessionLocal
from app.domain.health_data import SOURCE_TO_ACQUIRE_METHOD, is_biomarker_name, load_biomarker_keywords
from app.domain.scoring import grade_by_threshold
from app.pipeline.correction_terms import keyword_score
from app.pipeline.gate_matrix_table import GATE_MATRIX_TABLE, detect_invasive, is_invasive_hardcheck
from app.schemas.common import HealthDataItemInput, LegalBasis

router = APIRouter(prefix="/api/v1/judgement", tags=["judgement"])


class GateRequest(BaseModel):
    service_name: str
    service_description: str
    health_data_items: list[HealthDataItemInput]
    service_actions: list[str]


class GateResponse(BaseModel):
    data_type: str
    function_type: str
    acquire_method: str | None
    invasive_signal: bool
    verdict: str
    hardcheck_fired: bool


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


def _detect_invasive_signal(request: GateRequest) -> bool:
    # detect_invasive()는 내부에서 공백을 전부 지우고 매칭한다 — 서로 다른 필드를
    # 이어붙이면 경계가 사라져 부정표현/키워드가 필드를 가로질러 엉뚱하게 매칭된다.
    # 그래서 필드별로 따로 검사해 OR로 합친다.
    texts = [request.service_description] + [item.name for item in request.health_data_items]
    return any(detect_invasive(text) for text in texts)


@router.post("/gate", response_model=GateResponse)
async def judge_gate(request: GateRequest) -> GateResponse:
    async with AsyncSessionLocal() as session:
        biomarker_keywords = await load_biomarker_keywords(session)
    data_type = _classify_data_type(request.health_data_items, biomarker_keywords)
    function_type = _classify_function_type(request.service_actions)
    acquire_method = _classify_acquire_method(request.health_data_items)
    invasive_signal = _detect_invasive_signal(request)

    if is_invasive_hardcheck(data_type, acquire_method, invasive_signal):
        return GateResponse(
            data_type=data_type,
            function_type=function_type,
            acquire_method=acquire_method,
            invasive_signal=invasive_signal,
            verdict="FAIL",
            hardcheck_fired=True,
        )

    cell = GATE_MATRIX_TABLE[(data_type, function_type)]
    return GateResponse(
        data_type=data_type,
        function_type=function_type,
        acquire_method=acquire_method,
        invasive_signal=invasive_signal,
        verdict=cell["verdict"],
        hardcheck_fired=False,
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


async def _match_gate_keywords(service_description: str, rule_version_ids: list[uuid.UUID]) -> list[GateKeyword]:
    """gate_keywords를 단어 단위로 직접 매칭 — correction_rules.risky_text 문구 매칭보다 recall이 높다."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(GateKeyword).where(GateKeyword.rule_version_id.in_(rule_version_ids))
            )
        ).scalars().all()
    return [row for row in rows if row.keyword and row.keyword in service_description]


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
            legal_basis=LegalBasis(document_id=row.legal_basis_doc, article=row.legal_basis_article),
            exact_phrase_match=bool(phrase_hit),
        )
    return list(matched.values())


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


@router.post("/regulatory-risk", response_model=RegulatoryRiskResponse)
async def judge_regulatory_risk(request: GateRequest) -> RegulatoryRiskResponse:
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

    # matches는 matched_keywords에 의존해 이후 실행, 나머지 둘은 독립적이라 병렬 조회.
    matched_keywords, privacy_score = await asyncio.gather(
        _match_gate_keywords(request.service_description, rule_version_ids),
        _match_privacy_score(request.health_data_items),
    )
    matches = await _match_correction_rules(request.service_description, matched_keywords, rule_version_ids)
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
    )


# ---- judgement/correction-candidates ----


class CorrectionCandidate(BaseModel):
    risky_text: str
    safe_text: str
    legal_basis: LegalBasis
    exact_phrase_match: bool


class CorrectionCandidatesResponse(BaseModel):
    candidates: list[CorrectionCandidate]


@router.post("/correction-candidates", response_model=CorrectionCandidatesResponse)
async def judge_correction_candidates(request: GateRequest) -> CorrectionCandidatesResponse:
    rule_version_ids = await resolve_active_rule_version_ids()
    matched_keywords = await _match_gate_keywords(request.service_description, rule_version_ids)
    matches = await _match_correction_rules(request.service_description, matched_keywords, rule_version_ids)
    return CorrectionCandidatesResponse(
        candidates=[
            CorrectionCandidate(
                risky_text=m.risky_text,
                safe_text=m.safe_text,
                legal_basis=m.legal_basis,
                exact_phrase_match=m.exact_phrase_match,
            )
            for m in matches
        ]
    )
