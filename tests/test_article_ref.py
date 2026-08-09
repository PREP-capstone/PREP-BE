"""조문 표기 정규화 골든테스트 (db_구축_설계서.md §1.5.1).

이 값은 RAG `evidence_chunks.section_id`와의 join 키다. 어긋나면 예외 없이 조용히 조회가
실패하므로, §1.5.1 표에 실린 표기를 그대로 회귀 케이스로 고정한다.
"""

import pytest

from app.pipeline.article_ref import normalize_article


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 로마숫자 ASCII 통일 — Ⅲ(U+2162)와 III(영문 I 3개)는 다른 문자열이라 join이 깨진다
        ("Ⅲ.2.가", "III.2.가"),
        ("Ⅳ.1.가", "IV.1.가"),
        ("Ⅲ. 2. 가.", "III.2.가"),
        # 공백 제거 + 마침표 구분자
        ("부록2 Q11", "부록2.Q11"),
        ("별표7 제8호", "별표7.제8호"),
        # 조문 형태는 그대로 유지
        ("제23조", "제23조"),
        ("제45조", "제45조"),
        # 이미 정규화된 값은 멱등
        ("III.2.가", "III.2.가"),
        ("IV.3", "IV.3"),
        ("별표7.제18호", "별표7.제18호"),
        # 끝 마침표 제거
        ("IV.1.", "IV.1"),
    ],
)
def test_normalize_article(raw: str, expected: str) -> None:
    assert normalize_article(raw) == expected


def test_normalize_article_is_idempotent() -> None:
    """정규화를 두 번 걸어도 값이 변하지 않아야 한다 (파이프라인이 재실행돼도 join 키가 안정적)."""
    for raw in ("Ⅲ. 2. 가.", "부록2 Q11", "별표7 제8호"):
        once = normalize_article(raw)
        assert normalize_article(once) == once


@pytest.mark.parametrize("empty", [None, ""])
def test_normalize_article_passes_through_empty(empty) -> None:
    assert normalize_article(empty) == empty
