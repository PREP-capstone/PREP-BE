"""auto_validate의 순수 검증 함수 골든테스트 (DB·네트워크 불필요).

`auto_validate()` 자체는 DB를 조회하므로, Stage별 검증 로직만 떼어 직접 호출한다.
"""

from app.pipeline.nodes.validate import (
    _check_avoidance_fields,
    _check_citation,
    _check_citation_c,
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
    draft = {
        "fields": stage_b_fields(avoidance_redesign="기능 축소 안내", avoidance_certification="인증 트랙 안내")
    }
    assert _check_avoidance_fields(draft) == []


def test_avoidance_fields_pass_when_empty() -> None:
    """PASS/CONDITIONAL은 avoidance_*가 비어있어야 통과한다."""
    assert _check_avoidance_fields({"fields": stage_b_fields(verdict="PASS", priority=1)}) == []


def test_avoidance_fields_rejected_when_verdict_is_fail_but_empty() -> None:
    """FAIL인데 avoidance_*가 비어있으면(D-2 확정 후 채움 로직 누락 등) 필드누락으로 잡는다."""
    draft = {"fields": stage_b_fields(avoidance_redesign="기능 축소 안내", avoidance_certification=None)}
    assert _check_avoidance_fields(draft) == ["필드누락"]


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


# ---- 인용 대조: pypdf 추출 특성 흡수 ----


def test_citation_matches_across_mid_word_line_break() -> None:
    """회귀: 2단 편집 법령 PDF는 단어 중간에 줄바꿈이 들어간다("성생\n활").

    그대로 비교하면 LLM이 원문을 정확히 인용해도 전부 인용미확인으로 걸러져,
    실제로 1패스에서 법령 문서가 통째로 0행 적재됐다.
    """
    chunk = {"content": "개인정보처리자는 건강, 성생\n활 등에 관한 정보를 처리하여서는 아니 된다."}
    draft = {"fields": stage_b_fields(legal_basis={
        "document_id": "d", "article": "제23조", "quote": "건강, 성생활 등에 관한 정보",
    })}
    assert _check_citation(draft, [chunk]) == []


def test_citation_matches_when_extraction_drops_all_spaces() -> None:
    """별표7은 반대로 공백이 아예 없이 추출된다 — 이쪽도 통과해야 한다."""
    chunk = {"content": "1.의료기기의명칭ㆍ제조방법ㆍ성능이나효능및효과에관한거짓또는과대광고"}
    draft = {"fields": stage_b_fields(legal_basis={
        "document_id": "d", "article": "별표7.제1호", "quote": "의료기기의 명칭ㆍ제조방법ㆍ성능",
    })}
    assert _check_citation(draft, [chunk]) == []


def test_citation_still_rejects_fabricated_quote() -> None:
    """공백을 무시해도 원문에 없는 문장은 잡아내야 한다."""
    chunk = {"content": "개인정보처리자는 건강에 관한 정보를 처리하여서는 아니 된다."}
    draft = {"fields": stage_b_fields(legal_basis={
        "document_id": "d", "article": "제23조", "quote": "이 법은 2030년부터 시행한다",
    })}
    assert _check_citation(draft, [chunk]) == ["인용미확인"]


# ---- advertising_score=0("해당 없음")일 때 advertising_basis.quote 요구 면제 ----
# 회귀: 실제 약사법 추출("조현병 조제", advertising_score=0)이 quote=""라는 이유로
# 전량 필드누락 탈락했다. 0점은 인용할 별표7 항목 자체가 없는 게 정상이다(2026-08-14).


def test_stage_c_zero_ad_score_does_not_require_quote() -> None:
    draft = {
        "fields": stage_c_fields(
            advertising_score=0,
            advertising_basis={"attachment7_item": 0, "quote": ""},
        )
    }
    assert _check_required_fields_c(draft) == []


def test_stage_c_nonzero_ad_score_still_requires_quote() -> None:
    draft = {
        "fields": stage_c_fields(
            advertising_score=2,
            advertising_basis={"attachment7_item": 3, "quote": ""},
        )
    }
    assert _check_required_fields_c(draft) == ["필드누락"]


def test_stage_c_citation_skips_ad_basis_when_score_zero() -> None:
    draft = {
        "fields": stage_c_fields(
            advertising_score=0,
            advertising_basis={"attachment7_item": 0, "quote": ""},
        )
    }
    assert _check_citation_c(draft, [{"content": CHUNK_TEXT}]) == []


def test_stage_c_citation_still_checked_when_score_nonzero() -> None:
    draft = {
        "fields": stage_c_fields(
            advertising_score=1,
            advertising_basis={"attachment7_item": 12, "quote": "지어낸 문장"},
        )
    }
    assert _check_citation_c(draft, [{"content": CHUNK_TEXT}]) == ["인용미확인"]
