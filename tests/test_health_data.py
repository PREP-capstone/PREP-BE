"""app/domain/health_data.py 생체지표 판별 골든테스트.

load_biomarker_keywords()는 DB(gate_keywords) 조회가 필요해 여기서는 그게 반환하는
합집합을 그대로 재구성해서(BIOMARKER_EXTRA | GENETIC_TEST_KEYWORDS) is_biomarker_name()의
순수 로직만 검증한다 — DB 마킹 없이 돌아가는 회귀 테스트.
"""

from app.domain.health_data import _GATE_NON_BIOMARKER_DATA_TYPE_KEYWORDS, is_biomarker_name
from app.pipeline.correction_terms import BIOMARKER_EXTRA
from app.pipeline.genetic_test_actions import GENETIC_TEST_KEYWORDS

_KEYWORDS = set(BIOMARKER_EXTRA) | set(GENETIC_TEST_KEYWORDS)


def test_gate_non_biomarker_blacklist_excludes_disease_names_and_lifestyle_overrides() -> None:
    """이슈 1 회귀 — load_biomarker_keywords()가 화이트리스트 대신 블랙리스트를 쓰도록
    바꾼 이유(2026-09-27 코드리뷰): 판정엔진_개발설계서.md §5.1이 "생체지표 판별 사전은
    새 문서가 추가되면 자동으로 늘어난다"고 설계해서, 화이트리스트로 막으면 향후 파이프라인이
    새로 추출하는 진짜 생체지표 키워드까지 수동으로 코드에 추가하기 전엔 GATE에 반영이 안
    된다. 블랙리스트엔 질병명과 GATE 기준 라이프스타일 3개만 있어야 하고, 진짜 생체지표는
    빠져 있으면 안 된다."""
    assert "고혈압" in _GATE_NON_BIOMARKER_DATA_TYPE_KEYWORDS
    assert "당뇨" in _GATE_NON_BIOMARKER_DATA_TYPE_KEYWORDS
    assert "수면" in _GATE_NON_BIOMARKER_DATA_TYPE_KEYWORDS
    assert "스트레스" in _GATE_NON_BIOMARKER_DATA_TYPE_KEYWORDS
    assert "정신적 안정" in _GATE_NON_BIOMARKER_DATA_TYPE_KEYWORDS
    for biomarker in ("혈당", "혈압", "체온", "체지방"):
        assert biomarker not in _GATE_NON_BIOMARKER_DATA_TYPE_KEYWORDS


def test_genetic_test_item_names_match() -> None:
    """"유전자검사결과"류 항목명은 생체지표로 잡혀야 한다(2026-09-14 분류 버그 수정 대상)."""
    assert is_biomarker_name("유전자검사결과", _KEYWORDS) is True
    assert is_biomarker_name("유전체분석 리포트", _KEYWORDS) is True


def test_unrelated_genetic_looking_item_names_do_not_match() -> None:
    """"유전자변형식품"처럼 유전자검사와 무관한 항목명은 걸리면 안 된다.

    GENETIC_TEST_KEYWORDS가 "유전자검사"처럼 구체적인 복합어라 바로 이 오탐을 피한다 —
    한때 BIOMARKER_EXTRA에 넣었던 짧은 명사 "유전자"는 이런 항목명까지 걸렸었다
    (2026-09-14 코드리뷰로 발견).
    """
    assert is_biomarker_name("유전자변형식품 섭취여부", _KEYWORDS) is False
    assert is_biomarker_name("무유전자변형 원료 사용 여부", _KEYWORDS) is False


def test_existing_biomarker_extra_items_still_match() -> None:
    assert is_biomarker_name("심박수", _KEYWORDS) is True
    assert is_biomarker_name("체중", _KEYWORDS) is True
