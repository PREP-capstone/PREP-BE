"""법령 개정 알림의 관련/무관 판정 회귀 테스트.

실측 근거(2026-09-27): 감지된 개정 4건이 전부 무관이었다 — 의료법은 제5조가 바뀌었지만
우리는 제27조를 인용하고, 약사법은 제3조가 바뀌었지만 우리는 제2·23·24·44조를 인용한다.
교집합이 깨지면 이런 무관 알림이 배너를 채워 정작 중요한 건을 묻어버린다.
"""

from app.domain.law_amendment import (
    _article_keys,
    decide_relevance,
    filter_related_articles,
    find_missing_citations,
)


def _article(no: str, title: str = "제목") -> dict:
    return {"조문번호": no, "조문제목": title, "조문시행일자": "20260911", "본문": ""}


def test_parses_article_number_from_our_notation() -> None:
    assert _article_keys("제27조") == {"27"}


def test_keeps_branch_number_in_key() -> None:
    assert _article_keys("제24조의2") == {"24-2"}


def test_branch_citation_is_related_to_parent_article_change() -> None:
    """가지조문(제24조의2)을 인용 중이면 본조(제24조) 변경도 관련으로 본다(보수적)."""
    assert filter_related_articles([_article("24")], {"24-2"}) == [_article("24")]


def test_guideline_notation_yields_no_article_number() -> None:
    """지침서 표기(III.2.가)는 조문 번호가 아니라 교집합 대상이 아니다."""
    assert _article_keys("III.2.가") == set()


def test_filters_to_only_cited_articles() -> None:
    changed = [_article("5"), _article("27"), _article("56")]
    assert filter_related_articles(changed, {"27"}) == [_article("27")]


def test_unrelated_when_no_overlap() -> None:
    """의료법 실제 케이스 — 제5조가 바뀌었지만 우리는 제27조를 인용."""
    related = filter_related_articles([_article("5")], {"27"})
    assert related == []
    assert decide_relevance("kr-medical-act-20260407", related) == "unrelated"


def test_related_when_overlap_exists() -> None:
    related = filter_related_articles([_article("27")], {"27"})
    assert decide_relevance("kr-medical-act-20260407", related) == "related"


def test_detects_citation_to_deleted_article() -> None:
    """우리가 인용하는 조문이 현행 법령에서 사라지면 그 룰은 legal_basis_article 조인이
    깨져 근거를 못 찾는다. "제25조의4 삭제" 같은 실제 케이스가 있었다."""
    current = [_article("2"), _article("27")]
    assert find_missing_citations({"2", "27", "44"}, current) == ["제44조"]


def test_detects_deleted_branch_article_even_when_parent_remains() -> None:
    """제25조는 남아있고 제25조의4만 삭제된 경우 — 본조 번호로 접으면 못 잡는다."""
    current = [
        {"조문번호": "25", "조문키": "25"},
        {"조문번호": "25", "조문키": "25-2"},
    ]
    assert find_missing_citations({"25", "25-2", "25-4"}, current) == ["제25조의4"]


def test_no_missing_citation_when_all_articles_exist() -> None:
    current = [_article("2"), _article("27")]
    assert find_missing_citations({"2", "27"}, current) == []


def test_unmappable_document_is_treated_as_related() -> None:
    """document_id를 못 찾으면 교집합을 낼 수 없다 — "판단 불가"를 "무관"으로 접으면
    조용히 놓치므로 보수적으로 related로 둔다."""
    assert decide_relevance(None, []) == "related"
