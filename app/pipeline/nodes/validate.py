"""[6] 자동 검증 노드. draft["stage"]별로 분기한다.
Stage A: 필수필드/enum/weight범위/인용/중복 + FAIL_CONFIRMED 조건
Stage B: 필수필드/enum/인용/중복(data_type+function_type 조합) + 파생값(verdict) 일치 검증
Stage C: 필수필드/점수범위(0~3, regulatory·advertising 2축)/인용(legal_basis+advertising_basis)/
         중복(risky_text) + derived_from_keyword_id가 실제 gate_keywords row를 가리키는지 검증
"""

from sqlalchemy import func, select

from app.db.models import CorrectionRule, GateKeyword, GateMatrix
from app.db.session import AsyncSessionLocal
from app.pipeline.gate_matrix_table import (
    ACQUIRE_METHOD_ENUM,
    DATA_TYPE_ENUM,
    FUNCTION_TYPE_ENUM,
    GATE_MATRIX_TABLE,
    MATRIX_VERDICT_ENUM,
    is_invasive_hardcheck,
    needs_invasive_review,
)
from app.pipeline.pharmacy_actions import is_pharmacy_action
from app.pipeline.state import ExtractedDraft, PipelineState, ValidationResult

_TYPE_ENUM = {"DISEASE", "PROHIBITED_ACTION", "DOCTOR_REPLACEMENT"}
_KEYWORD_CATEGORY_ENUM = {"DIAGNOSIS", "TREATMENT", "DATA_TYPE", "OTHER"}
_DATA_TYPE_FOCUS_ENUM = {"IMAGING", "NUMERIC", "TEXT", "LIFESTYLE", "NONE"}
_KEYWORD_VERDICT_ENUM = {"FAIL_CANDIDATE", "CONTEXT_CHECK", "FAIL_CONFIRMED"}
_STAGE_A_REQUIRED_FIELDS = [
    "type",
    "keyword",
    "keyword_category",
    "data_type_focus",
    "verdict",
    "weight",
    "legal_basis",
]
_STAGE_B_REQUIRED_FIELDS = ["data_type", "function_type", "verdict", "legal_basis"]
_STAGE_C_REQUIRED_FIELDS = [
    "risky_text",
    "safe_text",
    "regulatory_score",
    "advertising_score",
    "advertising_basis",
    "legal_basis",
]


async def auto_validate(state: PipelineState) -> dict:
    failed_checks: list[str] = []
    valid_drafts: list[ExtractedDraft] = []
    seen_keywords: set[str] = set()
    seen_matrix_combos: set[tuple[str, str, str | None]] = set()
    seen_risky_texts: set[str] = set()

    existing_keywords = await _load_existing_keywords()
    existing_matrix_combos = await _load_existing_matrix_combos()
    existing_keyword_ids = await _load_existing_keyword_ids()
    existing_risky_texts = await _load_existing_risky_texts()

    for draft in state["drafts"]:
        if draft["stage"] == "A":
            checks = _validate_stage_a(draft, state["chunks"], seen_keywords, existing_keywords)
        elif draft["stage"] == "B":
            checks = _validate_stage_b(draft, state["chunks"], seen_matrix_combos, existing_matrix_combos)
        elif draft["stage"] == "C":
            checks = _validate_stage_c(
                draft, state["chunks"], seen_risky_texts, existing_risky_texts, existing_keyword_ids
            )
        else:
            checks = ["값오류"]  # Stage D는 아직 미구현

        if checks:
            failed_checks.extend(checks)
        else:
            valid_drafts.append(draft)
            if draft["stage"] == "A":
                seen_keywords.add(_normalize_keyword(draft["fields"]["keyword"]))
            elif draft["stage"] == "B":
                seen_matrix_combos.add(_matrix_combo(draft["fields"]))
            else:
                seen_risky_texts.add(draft["fields"]["risky_text"].strip().lower())

    validation: ValidationResult = {
        "passed": len(failed_checks) == 0,
        "failed_checks": sorted(set(failed_checks)),
    }
    return {"drafts": valid_drafts, "validation": validation}


async def _load_existing_keywords() -> set[str]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(func.lower(GateKeyword.keyword)))
        return {row[0] for row in result.all()}


async def _load_existing_matrix_combos() -> set[tuple[str, str, str | None]]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(GateMatrix.data_type, GateMatrix.function_type, GateMatrix.acquire_method)
        )
        return {(row[0], row[1], row[2]) for row in result.all()}


async def _load_existing_keyword_ids() -> set[str]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(GateKeyword.keyword_id))
        return {str(row[0]) for row in result.all()}


async def _load_existing_risky_texts() -> set[str]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(func.lower(CorrectionRule.risky_text)))
        return {row[0] for row in result.all()}


def _normalize_keyword(keyword: str) -> str:
    return keyword.strip().lower()


def _check_citation(draft: ExtractedDraft, chunks: list) -> list[str]:
    quote = draft["fields"]["legal_basis"]["quote"].strip()
    if not quote:
        return ["인용미확인"]
    for chunk in chunks:
        if quote in chunk["content"]:
            return []
    return ["인용미확인"]


# ---- Stage A ----


def _validate_stage_a(
    draft: ExtractedDraft, chunks: list, seen_keywords: set[str], existing_keywords: set[str]
) -> list[str]:
    checks = _check_required_fields_a(draft)
    if checks:
        return checks
    checks += _check_enums_a(draft)
    checks += _check_weight_range(draft)
    checks += _check_fail_confirmed_condition(draft)
    checks += _check_citation(draft, chunks)
    checks += _check_duplicate_keyword(draft, seen_keywords, existing_keywords)
    return checks


def _check_required_fields_a(draft: ExtractedDraft) -> list[str]:
    fields = draft.get("fields", {})
    for field_name in _STAGE_A_REQUIRED_FIELDS:
        if not fields.get(field_name) and fields.get(field_name) != 0:
            return ["필드누락"]

    legal_basis = fields["legal_basis"]
    for legal_field in ("document_id", "article", "quote"):
        if not legal_basis.get(legal_field):
            return ["필드누락"]
    return []


def _check_enums_a(draft: ExtractedDraft) -> list[str]:
    fields = draft["fields"]
    if (
        fields["type"] not in _TYPE_ENUM
        or fields["keyword_category"] not in _KEYWORD_CATEGORY_ENUM
        or fields["data_type_focus"] not in _DATA_TYPE_FOCUS_ENUM
        or fields["verdict"] not in _KEYWORD_VERDICT_ENUM
    ):
        return ["값오류"]
    return []


def _check_weight_range(draft: ExtractedDraft) -> list[str]:
    weight = draft["fields"]["weight"]
    if not isinstance(weight, int) or not (1 <= weight <= 5):
        return ["값오류"]
    return []


def _check_fail_confirmed_condition(draft: ExtractedDraft) -> list[str]:
    """FAIL_CONFIRMED를 구조적으로 인정하는 조건.

    - type=DOCTOR_REPLACEMENT: 의사 진단·처방 대체는 무조건 의료행위
    - weight=5: 고위해도 5요소 직접 해당
    - **약무행위 키워드** AND type=PROHIBITED_ACTION AND weight>=4 (2026-08-12 C안):
      weight 5의 정의를 "고위해도 5요소 전용"으로 유지한 채 regulatory_score 3점을 주기 위해
      verdict 쪽으로 표현하기로 했으므로, 검증도 같이 열어야 시드와 파이프라인 산출물이
      같은 모양이 된다.

      단 범위는 화이트리스트로 좁힌다. 처음엔 `PROHIBITED_ACTION AND weight>=4`로 넓게
      열었는데, LLM이 "자가 측정"·"진단·치료"까지 FAIL_CONFIRMED로 발급해 적재분 전부가
      3점(높음)으로 쏠렸다. 예외는 약무행위에만 준다.
    """
    fields = draft["fields"]
    if fields["verdict"] != "FAIL_CONFIRMED":
        return []
    if fields["type"] == "DOCTOR_REPLACEMENT":
        return []
    if fields["weight"] == 5:
        return []
    if (
        is_pharmacy_action(fields.get("keyword"))
        and fields["type"] == "PROHIBITED_ACTION"
        and fields["weight"] >= 4
    ):
        return []
    return ["값오류"]


def _check_duplicate_keyword(
    draft: ExtractedDraft, seen_keywords: set[str], existing_keywords: set[str]
) -> list[str]:
    normalized = _normalize_keyword(draft["fields"]["keyword"])
    if normalized in seen_keywords or normalized in existing_keywords:
        return ["중복후보"]
    return []


# ---- Stage B ----


def _validate_stage_b(
    draft: ExtractedDraft,
    chunks: list,
    seen_combos: set[tuple[str, str]],
    existing_combos: set[tuple[str, str]],
) -> list[str]:
    checks = _check_required_fields_b(draft)
    if checks:
        return checks
    checks += _check_enums_b(draft)
    checks += _check_derived_verdict(draft)
    checks += _check_avoidance_fields(draft)
    checks += _check_citation(draft, chunks)
    checks += _check_duplicate_combo(draft, seen_combos, existing_combos)
    return checks


def _check_required_fields_b(draft: ExtractedDraft) -> list[str]:
    fields = draft.get("fields", {})
    for field_name in _STAGE_B_REQUIRED_FIELDS:
        if not fields.get(field_name):
            return ["필드누락"]

    legal_basis = fields["legal_basis"]
    for legal_field in ("document_id", "article", "quote"):
        if not legal_basis.get(legal_field):
            return ["필드누락"]
    return []


def _check_enums_b(draft: ExtractedDraft) -> list[str]:
    fields = draft["fields"]
    if (
        fields["data_type"] not in DATA_TYPE_ENUM
        or fields["function_type"] not in FUNCTION_TYPE_ENUM
        or fields["verdict"] not in MATRIX_VERDICT_ENUM
    ):
        return ["값오류"]
    # acquire_method는 하드체크 전용 nullable 필드 — 값이 있을 때만 enum을 확인한다.
    acquire_method = fields.get("acquire_method")
    if acquire_method is not None and acquire_method not in ACQUIRE_METHOD_ENUM:
        return ["값오류"]
    return []


def _check_derived_verdict(draft: ExtractedDraft) -> list[str]:
    """verdict가 6칸 확정표와 일치하는지 확인.

    두 가지 예외를 허용한다.
    - 침습적 하드체크: 표 조회 이전에 FAIL로 오버라이드되므로 표와 달라지는 게 정상이다.
    - CONDITIONAL: 경계 케이스(3단계 폴백)나 침습 신호 불일치 결과로도 나올 수 있다.
    """
    fields = draft["fields"]
    data_type = fields["data_type"]
    acquire_method = fields.get("acquire_method")
    invasive_signal = bool(fields.get("invasive_signal"))

    if is_invasive_hardcheck(data_type, acquire_method, invasive_signal):
        return [] if fields["verdict"] == "FAIL" else ["파생값불일치"]
    if needs_invasive_review(
        data_type, acquire_method, invasive_signal, bool(fields.get("invasive_keyword_hit"))
    ):
        # 불일치 케이스는 검수 대기(CONDITIONAL)로 빠져야 한다 — FAIL도 표 값도 아니다.
        return [] if fields["verdict"] == "CONDITIONAL" else ["파생값불일치"]
    if fields["verdict"] == "CONDITIONAL":
        return []  # 경계 케이스(3단계 폴백) 결과일 수 있음 — 표 불일치로 보지 않음
    expected = GATE_MATRIX_TABLE.get((fields["data_type"], fields["function_type"]))
    if expected is None or expected["verdict"] != fields["verdict"]:
        return ["파생값불일치"]
    return []


def _check_avoidance_fields(draft: ExtractedDraft) -> list[str]:
    """avoidance_*는 verdict=FAIL일 때만 채울 수 있다 (db_구축_설계서.md §3.2).

    문구 작성 주체는 미정(D-2)이라 현재 파이프라인은 항상 None을 넣지만, 검증은 미리 걸어둔다.
    """
    fields = draft["fields"]
    if fields["verdict"] == "FAIL":
        return []
    if fields.get("avoidance_redesign") or fields.get("avoidance_certification"):
        return ["값오류"]
    return []


def _check_duplicate_combo(
    draft: ExtractedDraft,
    seen_combos: set[tuple[str, str, str | None]],
    existing_combos: set[tuple[str, str, str | None]],
) -> list[str]:
    """중복 키에 acquire_method를 포함한다.

    6칸 시드가 적재된 뒤에는 표에 이미 있는 조합이 다시 올라오면 중복으로 걸러지는 게 맞다
    (extract_b의 역할이 "신규 조합 탐지·QA"로 좁혀졌기 때문). 다만 침습적 하드체크 row는
    같은 (data_type, function_type)이라도 verdict가 다른 별개 row이므로, acquire_method를
    키에 넣어 시드 row(acquire_method=NULL)와 구분한다.
    """
    combo = _matrix_combo(draft["fields"])
    if combo in seen_combos or combo in existing_combos:
        return ["중복후보"]
    return []


def _matrix_combo(fields: dict) -> tuple[str, str, str | None]:
    return (fields["data_type"], fields["function_type"], fields.get("acquire_method"))


# ---- Stage C ----


def _validate_stage_c(
    draft: ExtractedDraft,
    chunks: list,
    seen_risky_texts: set[str],
    existing_risky_texts: set[str],
    existing_keyword_ids: set[str],
) -> list[str]:
    checks = _check_required_fields_c(draft)
    if checks:
        return checks
    checks += _check_score_range_c(draft)
    checks += _check_derived_from_keyword_exists(draft, existing_keyword_ids)
    checks += _check_citation_c(draft, chunks)
    checks += _check_duplicate_risky_text(draft, seen_risky_texts, existing_risky_texts)
    return checks


def _check_required_fields_c(draft: ExtractedDraft) -> list[str]:
    fields = draft.get("fields", {})
    for field_name in _STAGE_C_REQUIRED_FIELDS:
        value = fields.get(field_name)
        if not value and value != 0:
            return ["필드누락"]

    legal_basis = fields["legal_basis"]
    for legal_field in ("document_id", "article", "quote"):
        if not legal_basis.get(legal_field):
            return ["필드누락"]
    if not fields["advertising_basis"].get("quote"):
        return ["필드누락"]
    return []


def _check_score_range_c(draft: ExtractedDraft) -> list[str]:
    """privacy_score는 런타임 이관(§3.3.2)으로 검증 대상에서 빠졌다 — 2축만 확인한다."""
    fields = draft["fields"]
    for score_field in ("regulatory_score", "advertising_score"):
        score = fields[score_field]
        if not isinstance(score, int) or not (0 <= score <= 3):
            return ["값오류"]
    return []


def _check_derived_from_keyword_exists(draft: ExtractedDraft, existing_keyword_ids: set[str]) -> list[str]:
    derived_id = draft["fields"].get("derived_from_keyword_id")
    if derived_id is None:
        return []
    if derived_id not in existing_keyword_ids:
        return ["값오류"]
    return []


def _check_citation_c(draft: ExtractedDraft, chunks: list) -> list[str]:
    checks = _check_citation(draft, chunks)  # legal_basis.quote
    if checks:
        return checks

    quote = draft["fields"]["advertising_basis"]["quote"].strip()
    if not quote:
        return ["인용미확인"]
    for chunk in chunks:
        if quote in chunk["content"]:
            return []
    return ["인용미확인"]


def _check_duplicate_risky_text(
    draft: ExtractedDraft, seen_risky_texts: set[str], existing_risky_texts: set[str]
) -> list[str]:
    normalized = draft["fields"]["risky_text"].strip().lower()
    if normalized in seen_risky_texts or normalized in existing_risky_texts:
        return ["중복후보"]
    return []
