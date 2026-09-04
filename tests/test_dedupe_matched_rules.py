"""_dedupe_matched_rules 단위 테스트 — DB 불필요.

이슈 보고: 당뇨 진단 앱 테스트셋에서 regulatory-risk의 matched_rules에 완전히 동일한
근거 카드가 여러 번 뜨는 문제. generate_correction_rules.py의 combos()가 명사(당뇨/당뇨병
등)별로 별도 correction_rules 행을 만들지만 legal_basis(document_id/article)는 동사
단위로 동일해서 벌어진다.
"""

from app.api.judgement import CorrectionMatch, _dedupe_matched_rules
from app.schemas.common import LegalBasis


def _match(document_id: str, article: str, *, risky_text: str, exact_phrase_match: bool) -> CorrectionMatch:
    return CorrectionMatch(
        risky_text=risky_text,
        safe_text="안내",
        regulatory_score=2,
        advertising_score=0,
        legal_basis=LegalBasis(document_id=document_id, article=article, title="의료법"),
        exact_phrase_match=exact_phrase_match,
        match_source="rule",
    )


def test_same_legal_basis_collapses_into_one_entry() -> None:
    """당뇨 진단 / 당뇨병 진단 — risky_text만 다르고 legal_basis는 동일한 두 매치."""
    matches = [
        _match("kr-medical-act-20260407", "제27조", risky_text="당뇨 진단", exact_phrase_match=False),
        _match("kr-medical-act-20260407", "제27조", risky_text="당뇨병 진단", exact_phrase_match=False),
    ]

    result = _dedupe_matched_rules(matches)

    assert len(result) == 1
    assert result[0].legal_basis.document_id == "kr-medical-act-20260407"
    assert result[0].legal_basis.article == "제27조"


def test_exact_phrase_match_promotes_to_true_when_merged() -> None:
    """둘 중 하나라도 exact_phrase_match=True면 합쳐진 결과도 True를 유지해야 정보가 안 죽는다."""
    matches = [
        _match("kr-medical-act-20260407", "제27조", risky_text="당뇨 진단", exact_phrase_match=False),
        _match("kr-medical-act-20260407", "제27조", risky_text="당뇨병 진단", exact_phrase_match=True),
    ]

    result = _dedupe_matched_rules(matches)

    assert len(result) == 1
    assert result[0].exact_phrase_match is True


def test_different_articles_are_kept_separate() -> None:
    """document_id는 같아도 article이 다르면 서로 다른 근거이므로 둘 다 남아야 한다."""
    matches = [
        _match("kr-mfds-wellness-0091-03-20260212", "IV.1.가", risky_text="당뇨 검사", exact_phrase_match=True),
        _match("kr-mfds-wellness-0091-03-20260212", "IV.2.나", risky_text="당뇨 처방", exact_phrase_match=True),
    ]

    result = _dedupe_matched_rules(matches)

    assert len(result) == 2
    assert {m.legal_basis.article for m in result} == {"IV.1.가", "IV.2.나"}


def test_empty_input_returns_empty_list() -> None:
    assert _dedupe_matched_rules([]) == []
