"""classify_document_source 회귀 테스트 — 파일명 기준 규칙 분류, 관리자 수동 지정 시 존중."""

from app.pipeline.nodes.classify import classify_document_source


def test_classifies_statute_by_title_keyword() -> None:
    state = {"document_id": "의료기기법 시행규칙(총리령 제2127호)20260701"}
    assert classify_document_source(state) == {"document_category": "법령규제문서"}


def test_classifies_guideline_by_title_keyword() -> None:
    state = {"document_id": "모바일 의료용 앱 안전관리 지침"}
    assert classify_document_source(state) == {"document_category": "판단가이드"}


def test_defaults_to_guideline_when_no_keyword_matches() -> None:
    state = {"document_id": "이상한제목"}
    assert classify_document_source(state) == {"document_category": "판단가이드"}


def test_respects_manually_specified_category() -> None:
    """관리자가 이미 지정했으면 자동 분류로 덮어쓰지 않아야 한다."""
    state = {"document_id": "의료기기법 시행규칙", "document_category": "위험표현사전"}
    assert classify_document_source(state) == {}
