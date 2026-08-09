"""Stage B 6칸 확정표 정합성 + 침습적 하드체크 골든테스트.

6칸 표(db_구축_설계서.md §3.2)는 법령 원문 근거를 확보한 닫힌 확정표라, 값이 바뀌면 판정 결과가
통째로 달라진다. 특히 "혈당 수치 표시 + 위험수치 알람"(생체지표×수치예측·진단=FAIL)은 과거
프롬프트 변경으로 단순기록(PASS)으로 오분류된 전례가 있어 회귀 케이스로 고정한다
(구현_현황_정리.md §Stage B 검증).
"""

import pytest

from app.pipeline.gate_matrix_table import (
    DATA_TYPE_ENUM,
    FUNCTION_TYPE_ENUM,
    GATE_MATRIX_TABLE,
    HARDCHECK_VERDICT,
    MATRIX_VERDICT_ENUM,
    VERDICT_PRIORITY,
    detect_invasive,
    is_invasive_hardcheck,
)

# §3.2 확정 매핑표 — 표를 코드에서 읽어오지 않고 여기에 독립적으로 다시 적어 대조한다.
EXPECTED_MATRIX = {
    ("생체지표", "단순기록"): "PASS",
    ("생체지표", "비교·추이분석"): "CONDITIONAL",
    ("생체지표", "수치예측·진단"): "FAIL",
    ("라이프스타일", "단순기록"): "PASS",
    ("라이프스타일", "비교·추이분석"): "PASS",
    ("라이프스타일", "수치예측·진단"): "CONDITIONAL",
}


def test_matrix_has_exactly_six_cells() -> None:
    """2종 × 3종 = 6칸. 축이 늘어나면(예: acquire_method를 키에 넣으면) 여기서 잡힌다."""
    assert len(GATE_MATRIX_TABLE) == 6
    assert set(GATE_MATRIX_TABLE) == set(EXPECTED_MATRIX)


@pytest.mark.parametrize(("combo", "expected_verdict"), sorted(EXPECTED_MATRIX.items()))
def test_matrix_verdicts_match_design(combo: tuple[str, str], expected_verdict: str) -> None:
    assert GATE_MATRIX_TABLE[combo]["verdict"] == expected_verdict


def test_glucose_alarm_case_is_fail() -> None:
    """회귀 케이스: "혈당 수치값 표시 + 위험수치 알람"은 FAIL이어야 한다.

    과거 프롬프트 변경으로 단순기록(PASS)으로 오분류된 전례가 있는 조합이다.
    """
    assert GATE_MATRIX_TABLE[("생체지표", "수치예측·진단")]["verdict"] == "FAIL"


def test_glucose_alarm_example_stays_in_prompt() -> None:
    """오분류를 고친 예시 문구가 프롬프트에서 사라지지 않았는지 확인한다.

    이 문구를 프롬프트에서 빼면 같은 회귀가 재발한다 — 프롬프트 편집 사고를 잡는 가드다.
    """
    from app.pipeline.nodes.extract_b import _SYSTEM_PROMPT

    assert "혈당 수치값을 표시하고 위험 수치일 때 경고 알람을 제공" in _SYSTEM_PROMPT


def test_verdict_priority_orders_fail_first() -> None:
    """복수 조합 시 FAIL > CONDITIONAL > PASS (§3.2)."""
    assert VERDICT_PRIORITY["FAIL"] > VERDICT_PRIORITY["CONDITIONAL"] > VERDICT_PRIORITY["PASS"]
    assert set(VERDICT_PRIORITY) == MATRIX_VERDICT_ENUM


def test_enums_cover_matrix_keys() -> None:
    assert {data_type for data_type, _ in GATE_MATRIX_TABLE} == DATA_TYPE_ENUM
    assert {function_type for _, function_type in GATE_MATRIX_TABLE} == FUNCTION_TYPE_ENUM


# ---- 침습적 하드체크 (표 조회 이전 단계) ----


def test_hardcheck_fires_on_invasive_device_biometric() -> None:
    """생체지표 + 기기연동 + 침습적 → function_type과 무관하게 FAIL 오버라이드."""
    assert is_invasive_hardcheck("생체지표", "기기연동", True) is True
    assert HARDCHECK_VERDICT == "FAIL"


def test_hardcheck_overrides_a_pass_cell() -> None:
    """단순기록(표에서 PASS)이어도 하드체크가 걸리면 FAIL이 된다 — 오버라이드의 핵심."""
    assert GATE_MATRIX_TABLE[("생체지표", "단순기록")]["verdict"] == "PASS"
    assert is_invasive_hardcheck("생체지표", "기기연동", True) is True


@pytest.mark.parametrize(
    ("data_type", "acquire_method", "invasive_signal"),
    [
        ("라이프스타일", "기기연동", True),  # data_type이 생체지표가 아님
        ("생체지표", "수동입력", True),  # 기기연동이 아님
        ("생체지표", "OS연동", True),  # 기기연동이 아님
        ("생체지표", "기기연동", False),  # 침습적 신호 없음
        ("생체지표", None, True),  # 획득방법 미상
    ],
)
def test_hardcheck_does_not_fire_on_partial_match(
    data_type: str, acquire_method: str | None, invasive_signal: bool
) -> None:
    """세 조건이 모두 충족될 때만 발동한다 — 하나라도 빠지면 표 조회로 넘어가야 한다."""
    assert is_invasive_hardcheck(data_type, acquire_method, invasive_signal) is False


def test_detect_invasive_is_inert_until_d1_is_decided() -> None:
    """D-1(침습적 대상 목록) 미확정 상태에서는 코드 측 교차확인이 항상 False다.

    목록이 채워지면 이 테스트가 실패하면서 "이제 하드체크 입력이 하나 늘었다"는 신호가 된다.
    """
    assert detect_invasive("체내 삽입형 연속혈당측정기로 혈당을 측정한다") is False
