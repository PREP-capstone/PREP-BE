"""classify_document_source 회귀 테스트 — 파일명 기준 규칙 분류, 관리자 수동 지정 시 존중."""

from app.pipeline.document_id_normalize import normalize_document_id
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


def test_classifies_statute_from_source_title_after_id_normalization() -> None:
    """업로드 API가 실제로 넘기는 형태 — document_id는 이미 영문 slug로 정규화돼 있어
    한글 패턴이 남아있지 않으므로, 분류는 원본 제목(source_title)을 봐야 한다.
    (한글 제목만 넣는 테스트는 통과하는데 실제 경로는 전부 판단가이드로 떨어지던 버그)"""
    raw_title = "의료기기법(법률)(제21263호)(20260701"
    state = {
        "document_id": normalize_document_id(raw_title),
        "source_title": raw_title,
    }
    assert state["document_id"] == "kr-medical-device-act-20260701"
    assert classify_document_source(state) == {"document_category": "법령규제문서"}


def test_respects_manually_specified_category() -> None:
    """관리자가 이미 지정했으면 자동 분류로 덮어쓰지 않아야 한다."""
    state = {"document_id": "의료기기법 시행규칙", "document_category": "위험표현사전"}
    assert classify_document_source(state) == {}
