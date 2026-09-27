"""document_id 정규화 회귀 테스트 — 한글 파일명이 알려진 RAG document_id로 바뀌는지,
시행규칙처럼 더 구체적인 제목이 본법으로 잘못 매칭되지 않는지 확인한다."""

from app.pipeline.document_id_normalize import normalize_document_id


def test_normalizes_known_act_title() -> None:
    assert normalize_document_id("의료기기법(법률)(제21263호)(20260701") == "kr-medical-device-act-20260701"


def test_prefers_more_specific_title_over_substring() -> None:
    """"의료기기법 시행규칙"은 "의료기기법"의 상위 문자열을 포함하지만, 시행규칙 문서로
    정규화돼야지 본법(kr-medical-device-act-...)으로 잘못 매칭되면 안 된다."""
    assert (
        normalize_document_id("의료기기법 시행규칙(총리령 제2127호)20260701")
        == "kr-medical-device-act-rule-20260701"
    )


def test_unknown_title_passes_through_unchanged() -> None:
    raw = "생전처음보는법률(2026)"
    assert normalize_document_id(raw) == raw
