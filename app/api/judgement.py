"""판정 API — 1번 담당(Gate/규제 위험도 판정). 이슈 1: judgement/gate.

data_type/function_type/acquire_method/invasive_signal 판별은 규칙 기반이다(LLM 미사용).
analysis-sessions API가 아직 없어 요청 스키마는 역할분담표 §6 예시를 기준으로 임시 확정했다 —
실제 스키마 나오면 특히 health_data_items[].source(수집방법)·data_type(값 타입, GATE_MATRIX_TABLE의
data_type과 이름만 같고 뜻이 다름) 필드를 다시 맞춰야 한다.
"""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.db.models import CorrectionRule, DataSensitivity, GateKeyword, SignalConfig
from app.db.rule_version_queries import ACTIVE_RULE_VERSION_IDS
from app.db.session import AsyncSessionLocal
from app.pipeline.correction_terms import BIOMARKER_EXTRA
from app.pipeline.gate_matrix_table import GATE_MATRIX_TABLE, detect_invasive, is_invasive_hardcheck
from app.schemas.common import LegalBasis

router = APIRouter(prefix="/api/v1/judgement", tags=["judgement"])


class HealthDataItem(BaseModel):
    name: str
    data_type: str  # numeric/text/image 등 값 타입 — GATE_MATRIX_TABLE.data_type(라이프스타일/생체지표)과 다른 개념
    unit: str | None = None
    source: str  # user_input / device_sync / os_sync
    is_sensitive: bool = False


class GateRequest(BaseModel):
    service_name: str
    service_description: str
    health_data_items: list[HealthDataItem]
    service_actions: list[str]


class GateResponse(BaseModel):
    data_type: str
    function_type: str
    acquire_method: str | None
    invasive_signal: bool
    verdict: str
    hardcheck_fired: bool


_SOURCE_TO_ACQUIRE_METHOD = {
    "user_input": "수동입력",
    "device_sync": "기기연동",
    "os_sync": "OS연동",
}

# 여러 액션이 섞이면 가장 위험한 쪽 채택 (db_구축_설계서.md §3.2 "복수 조합 시 FAIL 우선").
_ACTION_PRIORITY: list[tuple[set[str], str]] = [
    ({"predict", "diagnose", "alert"}, "수치예측·진단"),
    ({"visualize_trend"}, "비교·추이분석"),
    ({"record"}, "단순기록"),
]

# 기기연동이어야 침습적 하드체크가 발동하므로 최우선.
_ACQUIRE_METHOD_PRIORITY = ("기기연동", "OS연동", "수동입력")


async def _biomarker_keywords() -> set[str]:
    """생체지표 판별 사전 = gate_keywords(DATA_TYPE) + BIOMARKER_EXTRA(Stage C와 공유, 미등록 지표 보충)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(GateKeyword.keyword).where(
                GateKeyword.rule_version_id.in_(ACTIVE_RULE_VERSION_IDS),
                GateKeyword.keyword_category == "DATA_TYPE",
            )
        )
        return set(result.scalars().all()) | set(BIOMARKER_EXTRA)


def _classify_data_type(items: list[HealthDataItem], biomarker_keywords: set[str]) -> str:
    for item in items:
        if any(keyword in item.name for keyword in biomarker_keywords):
            return "생체지표"
    return "라이프스타일"


def _classify_function_type(actions: list[str]) -> str:
    action_set = set(actions)
    for trigger_actions, function_type in _ACTION_PRIORITY:
        if action_set & trigger_actions:
            return function_type
    return "단순기록"


def _classify_acquire_method(items: list[HealthDataItem]) -> str | None:
    methods = {_SOURCE_TO_ACQUIRE_METHOD.get(item.source) for item in items}
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
    biomarker_keywords = await _biomarker_keywords()
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
    if score <= threshold_low:
        return "낮음"
    if score <= threshold_mid:
        return "중간"
    return "높음"


async def _signal_thresholds() -> dict[str, tuple[int, int]]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(SignalConfig).where(SignalConfig.rule_version_id.in_(ACTIVE_RULE_VERSION_IDS))
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


def _keyword_score(keyword_row: GateKeyword) -> int:
    """extract_c.py._keyword_score와 동일한 weight→score 변환. 오프라인/런타임 점수를 맞춘다."""
    if keyword_row.weight == 5 or keyword_row.verdict == "FAIL_CONFIRMED":
        return 3
    if keyword_row.weight in (3, 4):
        return 2
    if keyword_row.weight in (1, 2):
        return 1
    return 0


async def _match_gate_keywords(service_description: str) -> list[GateKeyword]:
    """gate_keywords를 단어 단위로 직접 매칭 — correction_rules.risky_text 문구 매칭보다 recall이 높다."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(GateKeyword).where(GateKeyword.rule_version_id.in_(ACTIVE_RULE_VERSION_IDS))
            )
        ).scalars().all()
    return [row for row in rows if row.keyword and row.keyword in service_description]


async def _match_correction_rules(
    service_description: str, matched_keywords: list[GateKeyword]
) -> list[CorrectionMatch]:
    """correction_rules를 두 경로로 매칭해 합친다(rule_id 기준 중복 제거).

    ① risky_text 문구 포함 ② derived_from_keyword_id로 matched_keywords와 역참조 연결
    (원래 반대 방향 추적용 FK를 거꾸로 탄, 더 관대한 매칭).
    """
    matched_keyword_ids = {row.keyword_id for row in matched_keywords}

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(CorrectionRule).where(CorrectionRule.rule_version_id.in_(ACTIVE_RULE_VERSION_IDS))
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


async def _match_privacy_score(items: list[HealthDataItem]) -> int:
    """health_data_items[].name을 data_sensitivity.item_label과 부분매칭해 최댓값 채택.

    ⚠️ 프론트 표기와 안 맞으면 조용히 0점 처리됨 — 확정되면(작업 #6) 정확히 맞출 것.
    """
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(DataSensitivity))).scalars().all()

    best = 0
    for item in items:
        name = item.name.strip()
        if not name:
            continue
        for row in rows:
            label = row.item_label.strip()
            if not label:
                continue
            if label in name or name in label:
                best = max(best, row.sensitivity_level)
    return best


@router.post("/regulatory-risk", response_model=RegulatoryRiskResponse)
async def judge_regulatory_risk(request: GateRequest) -> RegulatoryRiskResponse:
    # matches는 matched_keywords에 의존해 이후 실행, 나머지 셋은 독립적이라 병렬 조회.
    thresholds, matched_keywords, privacy_score = await asyncio.gather(
        _signal_thresholds(),
        _match_gate_keywords(request.service_description),
        _match_privacy_score(request.health_data_items),
    )
    missing_axes = [axis for axis in _AXIS_TO_SCORE_FIELD if axis not in thresholds]
    if missing_axes:
        raise HTTPException(
            status_code=500,
            detail=f"signal_config에 활성 임계값이 없는 축: {missing_axes}",
        )
    matches = await _match_correction_rules(request.service_description, matched_keywords)
    # 키워드/문구 두 매칭 중 더 높은 점수 채택 — 한쪽이 놓친 걸 다른 쪽으로 보강.
    keyword_score = max((_keyword_score(row) for row in matched_keywords), default=0)
    regulatory_score = max((m.regulatory_score for m in matches), default=0)
    regulatory_score = max(regulatory_score, keyword_score)
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
    matched_keywords = await _match_gate_keywords(request.service_description)
    matches = await _match_correction_rules(request.service_description, matched_keywords)
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
