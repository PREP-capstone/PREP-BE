"""[6] 자동 검증 노드. 필수필드/enum/weight범위/인용/중복 + FAIL_CONFIRMED 조건을 확인한다.
검증 실패 draft는 이번 배치에서만 제외(폐기 아님) — human_review가 붙으면 재시도/검수로 보내야 한다.
"""

from sqlalchemy import func, select

from app.db.models import GateKeyword
from app.db.session import AsyncSessionLocal
from app.pipeline.state import ExtractedDraft, PipelineState, ValidationResult

_TYPE_ENUM = {"DISEASE", "PROHIBITED_ACTION", "DOCTOR_REPLACEMENT"}
_KEYWORD_CATEGORY_ENUM = {"DIAGNOSIS", "TREATMENT", "DATA_TYPE", "OTHER"}
_DATA_TYPE_FOCUS_ENUM = {"IMAGING", "NUMERIC", "TEXT", "LIFESTYLE", "NONE"}
_VERDICT_ENUM = {"FAIL_CANDIDATE", "CONTEXT_CHECK", "FAIL_CONFIRMED"}
_REQUIRED_FIELDS = [
    "type",
    "keyword",
    "keyword_category",
    "data_type_focus",
    "verdict",
    "weight",
    "legal_basis",
]


async def auto_validate(state: PipelineState) -> dict:
    failed_checks: list[str] = []
    valid_drafts: list[ExtractedDraft] = []
    seen_keywords: set[str] = set()

    existing_keywords = await _load_existing_keywords()

    for draft in state["drafts"]:
        checks = _check_required_fields(draft)
        if not checks:
            checks += _check_enums(draft)
            checks += _check_weight_range(draft)
            checks += _check_fail_confirmed_condition(draft)
            checks += _check_citation(draft, state["chunks"])
            checks += _check_duplicate(draft, seen_keywords, existing_keywords)

        if checks:
            failed_checks.extend(checks)
        else:
            valid_drafts.append(draft)
            seen_keywords.add(_normalize_keyword(draft["fields"]["keyword"]))

    validation: ValidationResult = {
        "passed": len(failed_checks) == 0,
        "failed_checks": sorted(set(failed_checks)),
    }
    return {"drafts": valid_drafts, "validation": validation}


async def _load_existing_keywords() -> set[str]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(func.lower(GateKeyword.keyword)))
        return {row[0] for row in result.all()}


def _normalize_keyword(keyword: str) -> str:
    return keyword.strip().lower()


def _check_required_fields(draft: ExtractedDraft) -> list[str]:
    fields = draft.get("fields", {})
    for field_name in _REQUIRED_FIELDS:
        if not fields.get(field_name) and fields.get(field_name) != 0:
            return ["필드누락"]

    legal_basis = fields["legal_basis"]
    for legal_field in ("document_id", "article", "quote"):
        if not legal_basis.get(legal_field):
            return ["필드누락"]
    return []


def _check_enums(draft: ExtractedDraft) -> list[str]:
    fields = draft["fields"]
    if (
        fields["type"] not in _TYPE_ENUM
        or fields["keyword_category"] not in _KEYWORD_CATEGORY_ENUM
        or fields["data_type_focus"] not in _DATA_TYPE_FOCUS_ENUM
        or fields["verdict"] not in _VERDICT_ENUM
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


def _check_citation(draft: ExtractedDraft, chunks: list) -> list[str]:
    quote = draft["fields"]["legal_basis"]["quote"].strip()
    if not quote:
        return ["인용미확인"]
    for chunk in chunks:
        if quote in chunk["content"]:
            return []
    return ["인용미확인"]


def _check_duplicate(
    draft: ExtractedDraft, seen_keywords: set[str], existing_keywords: set[str]
) -> list[str]:
    normalized = _normalize_keyword(draft["fields"]["keyword"])
    if normalized in seen_keywords or normalized in existing_keywords:
        return ["중복후보"]
    return []
