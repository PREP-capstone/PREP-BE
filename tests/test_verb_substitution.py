"""verb_substitution 시드 데이터 + 조합 생성 로직 골든테스트 (DB 불필요)."""

from types import SimpleNamespace

import pytest

from scripts.generate_correction_rules import MEASURE_CAVEAT, combos
from scripts.seed_verb_substitution import ROWS as VERB_ROWS


def test_twelve_rows_with_expected_category_split() -> None:
    """2026-08-13 확정: DIAGNOSIS 4 / TREATMENT 5 / PHARM 3 = 12행."""
    assert len(VERB_ROWS) == 12
    by_category: dict[str, int] = {}
    for row in VERB_ROWS:
        by_category[row["verb_category"]] = by_category.get(row["verb_category"], 0) + 1
    assert by_category == {"DIAGNOSIS": 4, "TREATMENT": 5, "PHARM": 3}


def test_prevention_and_correction_verbs_excluded() -> None:
    """예방·보정은 웰니스판단기준 0091-03 원문이 PASS 예시로 쓰고 있어 제외했다."""
    verbs = {row["verb"] for row in VERB_ROWS}
    assert "예방" not in verbs
    assert "보정" not in verbs


def test_measure_is_biomarker_only() -> None:
    row = next(r for r in VERB_ROWS if r["verb"] == "측정")
    assert row["noun_classes"] == "생체지표"


def test_pharm_verbs_are_standalone_without_noun_classes() -> None:
    for verb in ("조제", "투약", "복약지도"):
        row = next(r for r in VERB_ROWS if r["verb"] == verb)
        assert row["standalone"] is True
        assert row["noun_classes"] == ""


def test_jojae_safe_verb_is_the_literal_no_substitute_notice() -> None:
    row = next(r for r in VERB_ROWS if r["verb"] == "조제")
    assert row["safe_verb"] == "대체 표현 없음 — 약사 전속 업무이므로 기능 자체를 제외해야 함"


# ---- combos() ----


def _verb(**overrides) -> SimpleNamespace:
    base = {"verb": "진단", "safe_verb": "확인", "noun_classes": "질병명", "standalone": False}
    base.update(overrides)
    return SimpleNamespace(**base)


def test_combos_pairs_every_noun_with_the_verb() -> None:
    pools = {"질병명": ["당뇨", "고혈압"]}
    pairs = list(combos(_verb(), pools))
    assert pairs == [("당뇨 진단", "당뇨 확인"), ("고혈압 진단", "고혈압 확인")]


def test_combos_standalone_ignores_noun_pools() -> None:
    verb = _verb(verb="조제", safe_verb="대체 표현 없음", standalone=True, noun_classes="")
    pairs = list(combos(verb, {"질병명": ["당뇨"]}))
    assert pairs == [("조제", "대체 표현 없음")]


def test_combos_measure_appends_caveat_to_safe_text_only() -> None:
    """caveat는 safe_text에만 붙는다 — risky_text는 순수 조합 그대로라 매칭에 영향 없다."""
    verb = _verb(verb="측정", safe_verb="변화 추이 확인", noun_classes="생체지표")
    pairs = list(combos(verb, {"생체지표": ["혈당"]}))
    assert pairs == [("혈당 측정", f"혈당 변화 추이 확인{MEASURE_CAVEAT}")]


def test_combos_pipe_separated_noun_classes_cover_all() -> None:
    verb = _verb(noun_classes="질병명|생체지표")
    pools = {"질병명": ["당뇨"], "생체지표": ["혈당"]}
    pairs = list(combos(verb, pools))
    assert {p[0] for p in pairs} == {"당뇨 진단", "혈당 진단"}


def test_combos_missing_noun_class_yields_nothing() -> None:
    """noun_classes에 적힌 계열이 pools에 없으면 조용히 0건 — KeyError로 죽지 않는다."""
    assert list(combos(_verb(noun_classes="상해장애"), {"질병명": ["당뇨"]})) == []


@pytest.mark.parametrize("verb", [row["verb"] for row in VERB_ROWS if row["verb"] != "측정"])
def test_only_measure_carries_the_caveat(verb: str) -> None:
    row = next(r for r in VERB_ROWS if r["verb"] == verb)
    ns = SimpleNamespace(**row)
    pools = {"질병명": ["당뇨"], "생체지표": ["혈당"]}
    for _, safe_text in combos(ns, pools):
        assert MEASURE_CAVEAT not in safe_text
