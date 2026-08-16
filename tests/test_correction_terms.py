"""correction_terms.py 명사 분류 상수 골든테스트."""

from app.pipeline.correction_terms import BIOMARKER_EXTRA, NOUN_CLASSIFICATION


def test_disease_and_biomarker_counts_match_decision() -> None:
    """2026-08-13 결정: DISEASE(DATA_TYPE) 14건이 질병명 7 / 생체지표 7로 나뉜다."""
    diseases = [k for k, v in NOUN_CLASSIFICATION.items() if v == "질병명"]
    biomarkers = [k for k, v in NOUN_CLASSIFICATION.items() if v == "생체지표"]
    assert len(diseases) == 7
    assert len(biomarkers) == 7


def test_hypertension_split_between_disease_and_biomarker() -> None:
    """고혈압/저혈압은 질병명, 혈압은 생체지표 — 겹침을 그대로 둔다(2026-08-13 결정)."""
    assert NOUN_CLASSIFICATION["고혈압"] == "질병명"
    assert NOUN_CLASSIFICATION["저혈압"] == "질병명"
    assert NOUN_CLASSIFICATION["혈압"] == "생체지표"


def test_biomarker_extra_has_five_items_not_in_gate_keywords() -> None:
    """심박수·체중·체성분·심전도·산소포화도는 gate_keywords에 없어 별도 상수로 둔다."""
    assert len(BIOMARKER_EXTRA) == 5
    assert set(BIOMARKER_EXTRA).isdisjoint(NOUN_CLASSIFICATION)
