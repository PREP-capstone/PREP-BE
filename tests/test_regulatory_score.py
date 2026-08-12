"""약무행위 키워드 → regulatory_score 산출 골든테스트 (2026-08-12 C안 확정).

배경: gate_keywords에 약무 키워드가 없으면 "맞춤형 영양제 처방" 같은 표현이
regulatory_score 0점으로 통과한다. C안은 weight 5의 정의("고위해도 5요소 전용")를
건드리지 않고 verdict=FAIL_CONFIRMED로 3점(높음)을 만드는 방식이다.

산출식(db_구축_설계서.md §3.3): weight=5 **또는** verdict=FAIL_CONFIRMED → 3점 /
weight 3~4 → 2점 / weight 1~2 → 1점 / 매칭 없음 → 0점
"""

import uuid

import pytest

from app.db.models import GateKeyword
from app.pipeline.nodes.extract_c import _derive_regulatory_score
from app.pipeline.nodes.validate import _check_fail_confirmed_condition
from scripts.seed_pharmacy_keywords import COMMON_FIELDS, PHARMACY_KEYWORDS


def keyword_row(keyword: str, weight: int, verdict: str) -> GateKeyword:
    """DB 없이 산출 로직만 검증하기 위한 인메모리 row."""
    return GateKeyword(
        keyword_id=uuid.uuid4(),
        rule_version_id=uuid.uuid4(),
        type="PROHIBITED_ACTION",
        keyword=keyword,
        keyword_category="TREATMENT",
        data_type_focus="NONE",
        verdict=verdict,
        weight=weight,
    )


def pharmacy_keywords() -> list[GateKeyword]:
    """시드 스크립트가 실제로 넣는 값 그대로 구성한다 — 시드가 바뀌면 같이 깨진다."""
    return [
        keyword_row(row["keyword"], row["weight"], COMMON_FIELDS["verdict"])
        for row in PHARMACY_KEYWORDS
    ]


def test_pharmacy_seed_uses_fail_confirmed_with_weight_4() -> None:
    """C안: weight는 4 그대로 두고 verdict로 3점을 만든다."""
    assert COMMON_FIELDS["verdict"] == "FAIL_CONFIRMED"
    assert {row["weight"] for row in PHARMACY_KEYWORDS} == {4}
    assert COMMON_FIELDS["keyword_category"] == "TREATMENT"  # enum 확장 없이 재사용


@pytest.mark.parametrize(
    "risky_text",
    ["맞춤형 영양제 처방", "약물 조제 서비스", "복약지도 제공", "투약 안내"],
)
def test_pharmacy_keywords_score_3(risky_text: str) -> None:
    """무면허 약무행위는 무면허 의료행위(진단·치료)와 같은 3점(높음)이어야 한다."""
    score, derived_id = _derive_regulatory_score(risky_text, pharmacy_keywords())
    assert score == 3
    assert derived_id is not None, "derived_from_keyword_id로 근거 키워드가 추적돼야 한다"


def test_fail_candidate_would_have_scored_only_2() -> None:
    """변경 전(FAIL_CANDIDATE) 값이면 2점에 그친다 — C안이 실제로 점수를 바꾼다는 증거."""
    before = [keyword_row("처방", 4, "FAIL_CANDIDATE")]
    assert _derive_regulatory_score("맞춤형 영양제 처방", before)[0] == 2


def test_unrelated_text_scores_0() -> None:
    score, derived_id = _derive_regulatory_score("걸음수 기록", pharmacy_keywords())
    assert score == 0
    assert derived_id is None


def test_validator_accepts_pharmacy_seed_shape() -> None:
    """시드가 만드는 모양(PROHIBITED_ACTION + weight 4 + FAIL_CONFIRMED)을 검증도 통과해야 한다.

    통과하지 못하면 파이프라인이 시드와 같은 값을 영원히 만들어낼 수 없다.
    """
    draft = {
        "fields": {
            "type": "PROHIBITED_ACTION",
            "keyword": "처방",
            "weight": 4,
            "verdict": "FAIL_CONFIRMED",
        }
    }
    assert _check_fail_confirmed_condition(draft) == []


def test_validator_still_rejects_low_weight_fail_confirmed() -> None:
    """구조적 안전장치는 유지 — weight 3 이하 PROHIBITED_ACTION은 여전히 값오류."""
    draft = {
        "fields": {
            "type": "PROHIBITED_ACTION",
            "keyword": "기록",
            "weight": 2,
            "verdict": "FAIL_CONFIRMED",
        }
    }
    assert _check_fail_confirmed_condition(draft) == ["값오류"]
