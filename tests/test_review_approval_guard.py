"""승인 전 구조 검증 회귀 테스트 — 행으로 만들 수 없는 draft는 그래프 재개 전에 막는다."""

import pytest
from fastapi import HTTPException

from app.api.rule_documents import DecisionItem, _reject_unpublishable_approvals
from app.pipeline.nodes.validate import structural_errors

_LEGAL_BASIS = {"document_id": "doc-1", "article": "제1조", "quote": "테스트 조문"}


def _draft(**field_overrides) -> dict:
    fields = {
        "type": "DISEASE",
        "keyword": "테스트키워드",
        "keyword_category": "DATA_TYPE",
        "data_type_focus": "NONE",
        "verdict": "FAIL_CANDIDATE",
        "weight": 2,
        "legal_basis": _LEGAL_BASIS,
        **field_overrides,
    }
    return {"stage": "A", "fields": fields, "legal_basis": _LEGAL_BASIS, "source_chunk_id": "chunk-1"}


def _item(draft: dict) -> dict:
    return {"draft": draft, "status": "validation_failed", "reasons": ["필드누락"]}


def test_structural_errors_passes_valid_draft() -> None:
    assert structural_errors(_draft()) == []


def test_structural_errors_flags_missing_field_and_bad_value() -> None:
    assert structural_errors(_draft(keyword="")) == ["필드누락"]
    assert structural_errors(_draft(weight="높음")) == ["값오류"]
    assert structural_errors({"stage": "D", "fields": {}}) == ["값오류"]


def test_approving_broken_draft_is_blocked() -> None:
    with pytest.raises(HTTPException) as error:
        _reject_unpublishable_approvals([_item(_draft(keyword=""))], [DecisionItem(action="approve")])
    assert error.value.status_code == 422


def test_rejecting_broken_draft_is_allowed() -> None:
    _reject_unpublishable_approvals([_item(_draft(keyword=""))], [DecisionItem(action="reject")])


def test_approving_with_fix_in_edited_fields_is_allowed() -> None:
    _reject_unpublishable_approvals(
        [_item(_draft(keyword=""))],
        [DecisionItem(action="approve", edited_fields={"keyword": "고친키워드"})],
    )


def test_edit_that_breaks_valid_draft_is_blocked() -> None:
    with pytest.raises(HTTPException):
        _reject_unpublishable_approvals(
            [_item(_draft())], [DecisionItem(action="approve", edited_fields={"weight": "높음"})]
        )
