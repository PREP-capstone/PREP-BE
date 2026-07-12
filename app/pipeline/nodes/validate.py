"""[6] 자동 검증 노드.

참고: docs/db_구축_설계서.md §4.4 자동 검증 규칙, docs/langgraph_파이프라인_설계서.md §7
Stage A 검증 항목: 필수필드/enum/weight 1~5 범위/인용/중복 + FAIL_CONFIRMED 4조건 매칭 확인
(파생값 일치 검증은 Stage C 전용이라 여기서는 대상 아님)

지금은 retry_extract/human_review 분기가 없으므로, 개별 draft가 검증에 실패하면
이번 실행에서는 publish 대상에서만 제외하고(자동 폐기가 아니라 "이번 배치에 포함 안 함"),
validation.failed_checks에 실패 사유를 남긴다. route_after_validate(설계서 §5.3)가 붙으면
실패건은 재시도/검수 큐로 보내야 한다.
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
    """FAIL_CONFIRMED 지정 기준 4조건 중 구조적으로 확인 가능한 부분만 검증.

    (1)고위해도 5요소, (2)의료기기 정의 4목적 명시는 문면 판단이 필요해 LLM/관리자 판단에 맡기고,
    여기서는 (3) type=DOCTOR_REPLACEMENT, (4) weight=5 AND type=DISEASE — 두 구조적 조건만
    자동 검증한다 (db_구축_설계서.md §4.2 FAIL_CONFIRMED 지정 기준).
    """
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
