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
    INVASIVE_KEYWORDS,
    MATRIX_VERDICT_ENUM,
    VERDICT_PRIORITY,
    detect_invasive,
    is_invasive_hardcheck,
    needs_invasive_review,
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


def test_invasive_criterion_is_stated_in_prompt() -> None:
    """침습 판단은 키워드 나열이 아니라 "각질층 관통" 기준으로 서술돼야 한다 (D-1).

    키워드만 나열하면 목록에 없는 신규 기기를 놓친다.
    """
    from app.pipeline.nodes.extract_b import _SYSTEM_PROMPT

    assert "각질층을 관통하는가" in _SYSTEM_PROMPT
    assert "마이크로니들" in _SYSTEM_PROMPT  # 패치 분기 예시가 살아 있는지


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


# ---- D-1 침습 판정: "각질층을 관통하는가" (2026-08-12 확정) ----


@pytest.mark.parametrize(
    "text",
    [
        "연속혈당측정기로 혈당을 측정한다",  # 센서를 피하에 삽입
        "CGM 센서를 부착해 사용한다",
        "채혈침으로 혈액을 채취한다",
        "란셋을 이용해 검체를 얻는다",
        "마이크로니들 패치를 사용한다",  # 패치지만 각질층 관통 → 침습
        "체내 삽입형 기기로 측정한다",
        "이식형 센서를 통해 수집한다",
        "침습적 방법으로 측정하는 경우",
        "정맥 천자로 채취한 검체",
        "피부를 침투하여 혈액을 채취하는 제품",  # 웰니스판단기준 0091-03 고위해도 예시 원문
    ],
)
def test_detect_invasive_matches_stratum_corneum_penetration(text: str) -> None:
    assert detect_invasive(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "광학식 센서로 심박수를 측정한다",
        "체중계로 체성분을 측정한다",
        "심전도 패치를 피부에 부착한다",  # 단순 부착형 → 비침습
        "패치 형태의 기기를 사용한다",  # "패치"만으로 침습 판정하면 안 된다
        "비침습적 방법으로 혈당을 추정한다",  # "침습"이 부분 문자열로 들어있는 함정
        "무침습 측정 기술을 적용한다",
        "혈당 수치값을 표시하고 위험 수치일 때 경고 알람을 제공",  # 혈당≠연속혈당
        "비침습적 및 비이식형 방법으로 측정한 혈압값을 표시한다",  # 웰니스판단기준 0091-03 원문
        "비삽입형 센서를 사용한다",  # "삽입형"이 부분 문자열로 들어있는 함정
    ],
)
def test_detect_invasive_ignores_non_penetrating_cases(text: str) -> None:
    assert detect_invasive(text) is False


def test_invasive_keywords_excludes_bare_patch() -> None:
    """형태 이름("패치")을 목록에 넣으면 비침습 부착형까지 전부 오탐한다."""
    assert "패치" not in INVASIVE_KEYWORDS


# ---- 안전장치: 코드 ↔ LLM 불일치는 FAIL이 아니라 검수 대기 ----


def test_keyword_hit_without_llm_signal_goes_to_review() -> None:
    """코드만 침습 신호를 잡은 경우 — 청크 단위 매칭이라 FAIL로 확정하지 않는다."""
    assert needs_invasive_review("생체지표", "기기연동", False, True) is True
    assert is_invasive_hardcheck("생체지표", "기기연동", False) is False


def test_confirmed_hardcheck_is_not_sent_to_review() -> None:
    """LLM이 침습이라고 한 경우는 이미 FAIL 확정이라 검수 대기로 중복 분기하지 않는다."""
    assert needs_invasive_review("생체지표", "기기연동", True, True) is False


@pytest.mark.parametrize(
    ("data_type", "acquire_method"),
    [("라이프스타일", "기기연동"), ("생체지표", "수동입력"), ("생체지표", None)],
)
def test_review_valve_requires_same_gate_as_hardcheck(
    data_type: str, acquire_method: str | None
) -> None:
    """검수 대기도 생체지표+기기연동 조합에서만 발동한다 — 무관한 조문을 끌어오지 않는다."""
    assert needs_invasive_review(data_type, acquire_method, False, True) is False


# ---- acquire_method 저장 조건 (§3.2: 하드체크 오버라이드 전용 필드) ----


def _stored_acquire_method(
    data_type: str, acquire_method: str | None, invasive_signal: bool, keyword_hit: bool
) -> str | None:
    """extract_b의 저장 조건을 그대로 재현한다."""
    fired = is_invasive_hardcheck(data_type, acquire_method, invasive_signal) or (
        needs_invasive_review(data_type, acquire_method, invasive_signal, keyword_hit)
    )
    return acquire_method if fired else None


def test_acquire_method_stored_only_when_hardcheck_fires() -> None:
    assert _stored_acquire_method("생체지표", "기기연동", True, False) == "기기연동"


def test_acquire_method_stored_when_review_fires() -> None:
    assert _stored_acquire_method("생체지표", "기기연동", False, True) == "기기연동"


@pytest.mark.parametrize(
    ("data_type", "acquire_method"),
    [
        ("생체지표", "단순기록"),
        ("생체지표", "수동입력"),
        ("생체지표", "OS연동"),
        ("라이프스타일", "기기연동"),
        ("라이프스타일", "수동입력"),
    ],
)
def test_acquire_method_blank_for_ordinary_combos(data_type: str, acquire_method: str) -> None:
    """발동하지 않는 일반 조합은 비워둔다.

    무조건 저장하면 생체지표×단순기록 같은 평범한 칸이 획득방법만 다른 중복 행으로 쌓인다.
    """
    assert _stored_acquire_method(data_type, acquire_method, False, False) is None
