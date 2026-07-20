"""[6] 자동 검증 노드. draft["stage"]별로 분기한다.
Stage A: 필수필드/enum/weight범위/인용/중복 + FAIL_CONFIRMED 조건
Stage B: 필수필드/enum/인용/중복(data_type+function_type 조합) + 파생값(verdict) 일치 검증
"""

from sqlalchemy import func, select

from app.db.models import GateKeyword, GateMatrix
from app.db.session import AsyncSessionLocal
from app.pipeline.gate_matrix_table import (
    DATA_TYPE_ENUM,
    FUNCTION_TYPE_ENUM,
    GATE_MATRIX_TABLE,
    MATRIX_VERDICT_ENUM,
)
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


async def auto_validate(state: PipelineState) -> dict:
    failed_checks: list[str] = []
    valid_drafts: list[ExtractedDraft] = []
    seen_keywords: set[str] = set()
    seen_matrix_combos: set[tuple[str, str]] = set()

    existing_keywords = await _load_existing_keywords()
    existing_matrix_combos = await _load_existing_matrix_combos()

    for draft in state["drafts"]:
        if draft["stage"] == "A":
            checks = _validate_stage_a(draft, state["chunks"], seen_keywords, existing_keywords)
        elif draft["stage"] == "B":
            checks = _validate_stage_b(draft, state["chunks"], seen_matrix_combos, existing_matrix_combos)
        else:
            checks = ["값오류"]  # Stage C/D는 아직 미구현

        if checks:
            failed_checks.extend(checks)
        else:
            valid_drafts.append(draft)
            if draft["stage"] == "A":
                seen_keywords.add(_normalize_keyword(draft["fields"]["keyword"]))
            else:
                seen_matrix_combos.add((draft["fields"]["data_type"], draft["fields"]["function_type"]))

    validation: ValidationResult = {
        "passed": len(failed_checks) == 0,
        "failed_checks": sorted(set(failed_checks)),
    }
    return {"drafts": valid_drafts, "validation": validation}


async def _load_existing_keywords() -> set[str]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(func.lower(GateKeyword.keyword)))
        return {row[0] for row in result.all()}


async def _load_existing_matrix_combos() -> set[tuple[str, str]]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(GateMatrix.data_type, GateMatrix.function_type))
        return {(row[0], row[1]) for row in result.all()}


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
    """FAIL_CONFIRMED는 type=DOCTOR_REPLACEMENT 또는 weight=5일 때만 구조적으로 인정."""
    fields = draft["fields"]
    if fields["verdict"] != "FAIL_CONFIRMED":
        return []
    if fields["type"] == "DOCTOR_REPLACEMENT":
        return []
    if fields["weight"] == 5:
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
    return []


def _check_derived_verdict(draft: ExtractedDraft) -> list[str]:
    """verdict가 6칸 확정표와 일치하는지 확인. CONDITIONAL은 경계 케이스 폴백으로도 나올 수 있어 허용."""
    fields = draft["fields"]
    if fields["verdict"] == "CONDITIONAL":
        return []  # 경계 케이스(3단계 폴백) 결과일 수 있음 — 표 불일치로 보지 않음
    expected = GATE_MATRIX_TABLE.get((fields["data_type"], fields["function_type"]))
    if expected is None or expected["verdict"] != fields["verdict"]:
        return ["파생값불일치"]
    return []


def _check_duplicate_combo(
    draft: ExtractedDraft, seen_combos: set[tuple[str, str]], existing_combos: set[tuple[str, str]]
) -> list[str]:
    combo = (draft["fields"]["data_type"], draft["fields"]["function_type"])
    if combo in seen_combos or combo in existing_combos:
        return ["중복후보"]
    return []
