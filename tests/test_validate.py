"""auto_validate의 순수 검증 함수 골든테스트 (DB·네트워크 불필요).

`auto_validate()` 자체는 DB를 조회하므로, Stage별 검증 로직만 떼어 직접 호출한다.
"""

from app.pipeline.nodes.validate import (
    _check_avoidance_fields,
    _check_derived_verdict,
    _check_enums_b,
    _check_required_fields_c,
    _check_score_range_c,
    _matrix_combo,
)

CHUNK_TEXT = "혈당 수치값을 표시하고 위험 수치일 때 경고 알람을 제공하는 앱은 의료기기에 해당한다."


def stage_b_fields(**overrides) -> dict:
    fields = {
        "data_type": "생체지표",
        "function_type": "수치예측·진단",
        "verdict": "FAIL",
        "exemption_note": None,
        "acquire_method": None,
        "invasive_signal": False,
        "avoidance_redesign": None,
        "avoidance_certification": None,
        "risk_code": None,
        "priority": 3,
        "legal_basis": {
            "document_id": "kr-mfds-wellness-0091-03-20260212",
            "article": "IV.3",
            "quote": CHUNK_TEXT,
        },
    }
    fields.update(overrides)
    return fields


def stage_c_fields(**overrides) -> dict:
    fields = {
        "risky_text": "당뇨 진단",
        "safe_text": "혈당 변화 확인",
        "regulatory_score": 3,
        "advertising_score": 0,
        "advertising_basis": {"attachment7_item": 1, "quote": CHUNK_TEXT},
        "derived_from_keyword_id": None,
        "legal_basis": {
            "document_id": "kr-medical-device-act-20260701",
            "article": "제2조",
            "quote": CHUNK_TEXT,
        },
    }
    fields.update(overrides)
    return fields


# ---- Stage B ----


def test_glucose_alarm_verdict_matches_table() -> None:
    """회귀 케이스: 생체지표×수치예측·진단은 FAIL이어야 통과한다."""
    assert _check_derived_verdict({"fields": stage_b_fields()}) == []


def test_glucose_alarm_misclassified_as_pass_is_rejected() -> None:
    """같은 조합을 PASS(단순기록 오분류)로 내면 파생값불일치로 걸러져야 한다."""
    draft = {"fields": stage_b_fields(verdict="PASS", priority=1)}
    assert _check_derived_verdict(draft) == ["파생값불일치"]


def test_hardcheck_fail_is_allowed_against_a_pass_cell() -> None:
    """하드체크가 걸린 row는 표(PASS)와 달라도 정상이다."""
    draft = {
        "fields": stage_b_fields(
            function_type="단순기록",
            verdict="FAIL",
            acquire_method="기기연동",
            invasive_signal=True,
        )
    }
    assert _check_derived_verdict(draft) == []


def test_hardcheck_row_must_be_fail() -> None:
    """하드체크 조건을 충족하는데 FAIL이 아니면 오버라이드가 누락된 것이다."""
    draft = {
        "fields": stage_b_fields(
            function_type="단순기록",
            verdict="PASS",
            acquire_method="기기연동",
            invasive_signal=True,
        )
    }
    assert _check_derived_verdict(draft) == ["파생값불일치"]


def test_acquire_method_enum_is_checked_only_when_present() -> None:
    assert _check_enums_b({"fields": stage_b_fields(acquire_method=None)}) == []
    assert _check_enums_b({"fields": stage_b_fields(acquire_method="기기연동")}) == []
    assert _check_enums_b({"fields": stage_b_fields(acquire_method="기관연동")}) == ["값오류"]


def test_avoidance_fields_rejected_when_verdict_is_not_fail() -> None:
    """avoidance_*는 verdict=FAIL 전용이다 (§3.2)."""
    draft = {
        "fields": stage_b_fields(
            function_type="단순기록", verdict="PASS", priority=1, avoidance_redesign="기능 축소 안내"
        )
    }
    assert _check_avoidance_fields(draft) == ["값오류"]


def test_avoidance_fields_allowed_when_verdict_is_fail() -> None:
    draft = {"fields": stage_b_fields(avoidance_certification="인증 트랙 안내")}
    assert _check_avoidance_fields(draft) == []


def test_avoidance_fields_pass_when_empty() -> None:
    """D-2 미확정으로 파이프라인이 항상 None을 넣는 현재 상태가 통과해야 한다."""
    assert _check_avoidance_fields({"fields": stage_b_fields(verdict="PASS", priority=1)}) == []


def test_matrix_combo_separates_hardcheck_row_from_seed_row() -> None:
    """시드 row(acquire_method=None)와 하드체크 row가 중복으로 뭉개지면 안 된다."""
    seed_row = _matrix_combo(stage_b_fields(function_type="단순기록", acquire_method=None))
    hardcheck_row = _matrix_combo(stage_b_fields(function_type="단순기록", acquire_method="기기연동"))
    assert seed_row != hardcheck_row


# ---- Stage C ----


def test_stage_c_passes_without_privacy_score() -> None:
    """privacy_score는 런타임 이관(§3.3.2)으로 더 이상 필수 필드가 아니다."""
    draft = {"fields": stage_c_fields()}
    assert _check_required_fields_c(draft) == []
    assert _check_score_range_c(draft) == []


def test_stage_c_score_range_ignores_privacy_score() -> None:
    """혹시 privacy_score가 남아 들어와도 2축만 검사하므로 영향이 없어야 한다."""
    draft = {"fields": stage_c_fields(privacy_score=99)}
    assert _check_score_range_c(draft) == []


def test_stage_c_rejects_out_of_range_scores() -> None:
    assert _check_score_range_c({"fields": stage_c_fields(regulatory_score=4)}) == ["값오류"]
    assert _check_score_range_c({"fields": stage_c_fields(advertising_score=-1)}) == ["값오류"]
