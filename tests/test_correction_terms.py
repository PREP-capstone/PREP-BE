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
    """심박수·체중·체성분·심전도·산소포화도는 gate_keywords에 없어 별도 상수로 둔다.

    유전자 관련 키워드는 여기 넣지 않는다(2026-09-14 코드리뷰로 발견) —
    generate_correction_rules.py가 이 목록을 통째로 noun pool에 넣어 모든
    verb_substitution 동사와 조합하므로, "유전자"를 넣으면 의료기기법 동사와 조합돼
    legal_basis가 어긋나는 correction_rules가 생성된다. 생체지표 판별 전용 확장은
    app/domain/health_data.py의 load_biomarker_keywords()가 genetic_test_actions.
    GENETIC_TEST_KEYWORDS를 별도로 union하는 방식으로 처리한다(test_health_data.py 참조).
    """
    assert len(BIOMARKER_EXTRA) == 5
    assert set(BIOMARKER_EXTRA).isdisjoint(NOUN_CLASSIFICATION)
