"""규제위험도 키워드 매칭의 부정 표현 인식 회귀 테스트(#141 R6).

GATE 의료 목적 하드체크와 같은 규칙(gate_matrix_table.is_negated_after)을 쓴다 — 같은 문장을
GATE는 부정으로, 규제위험도는 위험 표현으로 읽던 불일치를 막는다.
"""

import re

import pytest

from app.api.judgement import _compact_description, _has_unnegated_match
from app.pipeline.gate_matrix_table import scan_medical_purpose

_WHITESPACE = re.compile(r"\s+")


def _matches(description: str, keyword: str) -> bool:
    return _has_unnegated_match(_compact_description(description), _WHITESPACE.sub("", keyword))


@pytest.mark.parametrize(
    ("description", "keyword"),
    [
        # 검증 시나리오 R6 — 예전에는 키워드 뒤 5글자만 봐서 "진단"과 "질병"이 위험 표현으로 잡혔다.
        ("질병을 진단하거나 치료하지 않고 걸음수만 기록한다.", "진단"),
        ("질병을 진단하거나 치료하지 않고 걸음수만 기록한다.", "질병"),
        ("질병을 진단하거나 치료하지 않고 걸음수만 기록한다.", "치료"),
        # 운영 입력에서 나온 문장들(2026-10-06 RDS)
        ("별도의 진단이나 예측 없이 시간대별 심박수 그래프만 보여줍니다", "진단"),
        ("의료적 진단이나 치료를 대신하지 않고 생활 습관 개선만 돕습니다", "진단"),
        ("수치를 진단하거나 위험을 경고하지 않고, 지난 기록과 비교만 합니다", "진단"),
        ("화장품이나 시술을 직접 판매하지 않고 정보 제공에만 집중합니다", "시술"),
        # 기존 동작 유지
        ("복약지도를 하지 않고 단순 정보만 제공한다.", "복약지도"),
        ("복약지도를 하지는 않습니다.", "복약지도"),
        ("이 서비스는 질병 진단 목적이 아닙니다", "진단"),
        ("질병을 진단할 수 있는 것은 아닙니다", "진단"),
        ("질병을 진단하기 위한 서비스가 아닙니다", "진단"),
    ],
)
def test_negated_keyword_is_not_matched(description: str, keyword: str) -> None:
    assert not _matches(description, keyword)


@pytest.mark.parametrize(
    ("description", "keyword"),
    [
        ("수면 패턴을 분석해 불면증을 진단하고 맞춤 치료법을 처방한다", "진단"),
        # 부정이 다른 말에 걸린 경우 — 위험 표현을 놓치면 등급이 낮게 나간다.
        ("불면증을 진단하고 무리한 운동은 권하지 않습니다", "진단"),
        ("혈당을 진단해 부담 없이 관리하도록 돕습니다", "진단"),
        ("진단 결과를 알려주고 병원은 추천하지 않는다", "진단"),
        ("질병을 예측하고 약은 권하지 않는다", "질병"),
        # "~할 수 있어/하므로/하니 …하지 않아도 됩니다" — 키워드는 긍정이고 가장 위험한 문구다.
        ("불면증을 진단할 수 있어 병원에 가지 않아도 됩니다", "진단"),
        ("혈당 수치를 예측할 수 있고 병원 방문은 필요하지 않습니다", "예측"),
        ("우울증을 치료하므로 약을 먹지 않아도 됩니다", "치료"),
        ("당뇨를 진단하니 병원에 가지 않아도 됩니다", "진단"),
        # 마침표 없이 줄만 바꿔 쓴 입력 — 다음 줄의 부정이 넘어오지 않는다.
        ("질병을 진단\n광고는 하지 않음", "진단"),
        # 절이 바뀌면 부정이 넘어오지 않는다.
        ("질병을 진단합니다. 개인정보는 저장하지 않습니다", "진단"),
        ("질병을 진단하며, 광고는 보여주지 않습니다", "진단"),
        # "아니"가 든 무관한 단어(2026-09-27 코드리뷰에서 확인된 오탐)
        ("복약지도와 아니메이션 튜토리얼을 함께 제공합니다.", "복약지도"),
        ("치료 음악 피아니스트 매칭", "치료"),
        # 부정된 곳과 긍정인 곳이 함께 있으면 매칭된다.
        ("질병을 진단하지 않는다고 하지만 실제로는 불면증을 진단한다", "진단"),
    ],
)
def test_asserted_keyword_is_matched(description: str, keyword: str) -> None:
    assert _matches(description, keyword)


@pytest.mark.parametrize(
    "description",
    [
        "질병을 진단하거나 치료하지 않고 걸음수만 기록한다.",
        "의료적 진단이나 치료를 대신하지 않고 생활 습관 개선만 돕습니다",
        "불면증을 진단하고 무리한 운동은 권하지 않습니다",
        "수면 패턴을 분석해 불면증을 진단하고 맞춤 치료법을 처방한다",
        "불면증을 진단할 수 있어 병원에 가지 않아도 됩니다",
        "당뇨를 진단하니 병원에 가지 않아도 됩니다",
        "질병을 진단\n광고는 하지 않음",
        "질병을 진단할 수 있는 것은 아닙니다",
    ],
)
def test_gate_and_regulatory_read_negation_the_same_way(description: str) -> None:
    """GATE가 의료 목적으로 본 문장은 규제위험도에서도 "진단"이 잡히고, 부정으로 넘긴 문장은 안 잡힌다."""
    asserted_by_gate = scan_medical_purpose(description)[0] is not None
    assert _matches(description, "진단") is asserted_by_gate
