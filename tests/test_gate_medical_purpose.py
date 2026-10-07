"""의료 목적 하드체크(#141 S5) — 설명문의 진단·치료·처방 목적 표현을 GATE가 반영하는지.

감지 함수는 DB 없이, judge_gate는 test_gate_legal_basis.py와 같은 방식으로 DB 의존을 모킹해 돈다.
"""

from types import SimpleNamespace

import pytest

import app.api.judgement as judgement
from app.api.judgement import GateRequest, judge_gate
from app.pipeline.gate_matrix_table import MEDICAL_PURPOSE_LEGAL_BASIS, detect_medical_purpose
from app.schemas.common import HealthDataItemInput


@pytest.mark.parametrize(
    "description",
    [
        "수면 패턴을 분석해 불면증을 진단하고 맞춤 치료법과 영양제를 처방한다.",  # 검증 S5
        "걸음 데이터를 바탕으로 사용자의 질환 여부를 진단하고 맞춤 치료 방법을 처방하며 복약 지도까지 제공",
        "혈당 데이터를 분석해 당뇨병 여부를 진단하고 인슐린 처방 필요 여부를 알려준다",
        "담당 의료진과 동일한 기준으로 상태를 판정해서 사용자에게 진단 결과를 직접 통보하는 서비스",
        "100% 개선하고 확실히 치료 효과를 보장하는 웰니스 앱",
        "장기적으로는 병원과 제휴해 처방 연계 서비스로 확장하려 합니다.",
        "불면증을 진단하고 무리한 운동은 권하지 않습니다",  # 뒤의 부정은 다른 행위에 걸린다
        "증상을 진단하고 치료는 하지 않는다",  # 진단은 한다
    ],
)
def test_detects_asserted_medical_purpose(description: str) -> None:
    assert detect_medical_purpose(description) is not None


@pytest.mark.parametrize(
    "description",
    [
        "질병을 진단하거나 치료하지 않고 걸음수만 기록한다.",  # 검증 R6
        "생활습관 개선을 목표로 하며, 의료적 진단이나 치료를 대신하지 않습니다.",
        "측정값을 보여주는 관리 서비스입니다. 수치를 진단하거나 위험을 경고하지 않습니다.",
        "심박수를 수집하고, 별도의 진단이나 예측 없이 시간대별 그래프만 보여줍니다.",
        "진단 목적이 아닌 생활 기록 앱입니다.",
        "진단 기능은 없습니다",
        "병원에서 받은 진단명과 처방전을 기록해 두는 앱",
        "치료 중인 환자가 운동 일지를 남기는 앱",
        "처방받은 약의 복용 시간을 기록한다",
        "취침·기상 시간을 기록하고 주간 수면 패턴 리포트를 보여준다.",  # 검증 S4
        "수면 상태를 모니터링하고 생활습관에 대해 조언한다.",  # 검증 R4
        "이 앱만 쓰면 불면증이 100% 사라지고 부작용도 없다.",  # 검증 R8 — 광고 축의 문제, GATE 대상 아님
    ],
)
def test_ignores_negated_or_record_only_expressions(description: str) -> None:
    assert detect_medical_purpose(description) is None


def test_returns_phrase_around_the_keyword() -> None:
    phrase = detect_medical_purpose("수면 패턴을 분석해 불면증을 진단하고 맞춤 치료법을 제시한다.")
    assert "진단" in phrase
    assert "불면증" in phrase


def _patch(monkeypatch, description: str, items: list[HealthDataItemInput], actions: list[str]) -> None:
    async def fake_load_session(session_id: str):
        return SimpleNamespace(service_description=description, service_actions=actions), items

    async def fake_biomarker_keywords(session) -> set[str]:
        return {"심박수", "혈당"}

    async def fake_lookup(request):
        return SimpleNamespace(result=[SimpleNamespace(section_id="제2조", chunk_text="제2조(정의) ...")])

    monkeypatch.setattr(judgement, "_load_session", fake_load_session)
    monkeypatch.setattr(judgement, "load_biomarker_keywords", fake_biomarker_keywords)
    monkeypatch.setattr(judgement, "lookup_rag_chunks", fake_lookup)


_SLEEP = [HealthDataItemInput(name="수면 시간", data_type="numeric", source="os_sync", item_code="lifestyle_002")]


async def test_record_only_selection_with_diagnosis_description_is_fail(monkeypatch) -> None:
    """S5 — 기능은 기록만 골랐지만 설명이 진단·치료·처방을 말하면 FAIL."""
    _patch(monkeypatch, "수면 패턴을 분석해 불면증을 진단하고 맞춤 치료법과 영양제를 처방한다.", _SLEEP, ["record"])

    response = await judge_gate(GateRequest(session_id="unit-test"))

    assert response.verdict == "FAIL"
    assert response.medical_purpose_fired is True
    assert "진단" in response.medical_purpose_phrase
    assert response.hardcheck_fired is False
    assert (response.legal_basis.document_id, response.legal_basis.article) == MEDICAL_PURPOSE_LEGAL_BASIS
    assert response.legal_basis.quote_status == "FOUND"
    assert response.avoidance_redesign and response.avoidance_certification
    assert len(response.reasoning) == 4
    assert "PASS이지만" in response.reasoning[-1]
    assert response.medical_purpose_phrase in response.reasoning[2]


async def test_lifestyle_diagnose_selection_with_diagnosis_description_is_fail(monkeypatch) -> None:
    """S6 — 라이프스타일×수치예측·진단은 표로는 CONDITIONAL이지만 설명이 질병 진단을 말하면 FAIL."""
    _patch(
        monkeypatch, "수면 패턴을 분석해 불면증을 진단하고 맞춤 치료법과 영양제를 처방한다.", _SLEEP, ["record", "diagnose"]
    )

    response = await judge_gate(GateRequest(session_id="unit-test"))

    assert response.verdict == "FAIL"
    assert response.medical_purpose_fired is True
    assert "CONDITIONAL이지만" in response.reasoning[-1]


async def test_negated_description_keeps_matrix_verdict(monkeypatch) -> None:
    """R6 — "진단하거나 치료하지 않고"는 의료 목적이 아니므로 표의 PASS가 그대로 나온다."""
    steps = [HealthDataItemInput(name="걸음수", data_type="numeric", source="os_sync", item_code="lifestyle_001")]
    _patch(monkeypatch, "질병을 진단하거나 치료하지 않고 걸음수만 기록한다.", steps, ["record"])

    response = await judge_gate(GateRequest(session_id="unit-test"))

    assert response.verdict == "PASS"
    assert response.medical_purpose_fired is False
    assert response.medical_purpose_phrase is None


async def test_matrix_fail_keeps_its_own_basis(monkeypatch) -> None:
    """표가 이미 FAIL이면(생체지표×수치예측·진단) 의료 목적 하드체크는 끼어들지 않는다 — 근거는 매트릭스 칸."""
    glucose = [HealthDataItemInput(name="혈당", data_type="numeric", source="user_input", item_code="sensitive_001")]
    _patch(monkeypatch, "혈당을 분석해 당뇨병 여부를 진단한다.", glucose, ["predict"])

    response = await judge_gate(GateRequest(session_id="unit-test"))

    assert response.verdict == "FAIL"
    assert response.medical_purpose_fired is False
    assert response.legal_basis.article == "IV.3"


@pytest.mark.parametrize(
    "description",
    ["AI 불면증 진단 서비스입니다", "피부 치료 전문 코칭을 제공한다", "치료 중심의 재활 프로그램을 제공"],
)
def test_record_suffix_exclusions_do_not_hide_service_expressions(description: str) -> None:
    assert detect_medical_purpose(description) is not None


@pytest.mark.parametrize(
    "description",
    [
        # 부정이 키워드가 아닌 다른 말에 걸린 경우 — 의료 목적을 놓치면 FAIL이 PASS로 나간다.
        "불면증을 진단해 부담 없이 관리하도록 돕는다",
        "우울증을 진단하는 앱으로 개인정보를 서버에 저장하지 않습니다",
        "수면무호흡을 진단하며 부작용이 없는 관리법을 안내한다",
        "AI로 우울증을 진단받을 수 있는 서비스",
        "증상에 맞는 처방 약국 연계 서비스를 제공한다",
    ],
)
def test_negation_on_another_phrase_does_not_hide_medical_purpose(description: str) -> None:
    assert detect_medical_purpose(description) is not None


@pytest.mark.parametrize(
    "description",
    [
        "진단해 주지 않습니다. 기록만 합니다.",
        "질병을 진단하는 것이 아니라 생활 기록을 돕습니다",
        "진단 및 치료를 목적으로 하지 않습니다",
        "병원에서 진단받은 내용을 메모해 두는 앱",
    ],
)
def test_negation_attached_to_the_keyword_is_respected(description: str) -> None:
    assert detect_medical_purpose(description) is None


async def test_negated_expression_is_reported_without_changing_verdict(monkeypatch) -> None:
    """부정 문맥으로 보고 넘긴 경우 — 판정은 표의 결과 그대로지만 넘긴 문구와 안내 한 줄이 응답에 남는다."""
    steps = [HealthDataItemInput(name="걸음수", data_type="numeric", source="os_sync", item_code="lifestyle_001")]
    _patch(monkeypatch, "질병을 진단하거나 치료하지 않고 걸음수만 기록한다.", steps, ["record"])

    response = await judge_gate(GateRequest(session_id="unit-test"))

    assert response.verdict == "PASS"
    assert response.medical_purpose_fired is False
    assert "진단하거나 치료하지" in response.medical_purpose_negated_phrase
    assert len(response.reasoning) == 5
    assert response.medical_purpose_negated_phrase in response.reasoning[-1]
    assert "반영하지 않았습니다" in response.reasoning[-1]


async def test_no_note_when_description_has_no_medical_expression(monkeypatch) -> None:
    _patch(monkeypatch, "취침·기상 시간을 기록하고 주간 수면 패턴 리포트를 보여준다.", _SLEEP, ["record"])

    response = await judge_gate(GateRequest(session_id="unit-test"))

    assert response.medical_purpose_negated_phrase is None
    assert len(response.reasoning) == 4


async def test_record_expressions_are_neither_fired_nor_reported(monkeypatch) -> None:
    """"진단명", "처방전"은 의료 목적과 무관한 기록 표현이라 안내도 붙지 않는다."""
    _patch(monkeypatch, "병원에서 받은 진단명과 처방전을 기록해 두는 앱", _SLEEP, ["record"])

    response = await judge_gate(GateRequest(session_id="unit-test"))

    assert response.verdict == "PASS"
    assert response.medical_purpose_negated_phrase is None
    assert len(response.reasoning) == 4


@pytest.mark.parametrize(
    "description",
    [
        # 질병과 무관한 "진단"·"처방" — 의료기기법 제2조의 대상은 "질병의" 진단·치료다.
        "피부 상태를 진단해 맞춤 화장품을 추천한다",
        "퍼스널컬러를 진단하고 어울리는 색을 알려준다",
        "체형에 맞는 운동 처방과 식단 처방을 제공한다",
        # 사람·장소·비용을 가리키는 복합어
        "물리치료사와 사용자를 연결하는 매칭 플랫폼",
        "근처 심리치료센터 위치와 치료비를 비교해 보여준다",
        # 건강검진·자가 점검·기록
        "회사 건강진단 결과를 기록해 두고 연도별로 비교한다",
        "병원 진단 결과를 입력하면 일정에 맞춰 복약 알림을 준다",
        "스트레스 자가진단 설문으로 현재 상태를 점검한다",
        "처방약 복용 시간을 기록한다",
    ],
)
def test_non_medical_usages_are_not_treated_as_medical_purpose(description: str) -> None:
    assert detect_medical_purpose(description) is None


@pytest.mark.parametrize(
    "description",
    [
        "AI가 탈모를 진단하고 치료 방법을 안내한다",
        "증상을 입력하면 질병을 진단해 줍니다",
        "피부 질환을 진단해 맞춤 관리법을 추천한다",
        "증상에 맞는 치료약을 추천해 준다",
        "혈당 수치에 따라 인슐린을 처방해 준다",
    ],
)
def test_disease_context_keeps_medical_purpose(description: str) -> None:
    assert detect_medical_purpose(description) is not None


async def test_non_medical_usage_gets_neither_fail_nor_note(monkeypatch) -> None:
    """"피부 상태 진단"은 질병 진단이 아니라 표의 판정 그대로이고, 부정 문맥이 아니므로 안내도 붙지 않는다."""
    _patch(monkeypatch, "피부 상태를 진단해 맞춤 화장품을 추천한다", _SLEEP, ["record"])

    response = await judge_gate(GateRequest(session_id="unit-test"))

    assert response.verdict == "PASS"
    assert response.medical_purpose_fired is False
    assert response.medical_purpose_negated_phrase is None
    assert len(response.reasoning) == 4


async def test_disease_self_check_keeps_verdict_and_adds_note(monkeypatch) -> None:
    """병명 + 자가진단 — FAIL로 올리지 않고, 병명을 판정하는 기능인지 확인하라는 안내만 붙인다."""
    _patch(monkeypatch, "우울증 자가진단 테스트를 제공하고 결과를 기록한다.", _SLEEP, ["record"])

    response = await judge_gate(GateRequest(session_id="unit-test"))

    assert response.verdict == "PASS"
    assert response.medical_purpose_fired is False
    assert "우울증 자가진단" in response.medical_purpose_self_check_phrase
    assert response.medical_purpose_negated_phrase is None
    assert len(response.reasoning) == 5
    assert "자가진단 표현" in response.reasoning[-1]
    assert "병명을 판정" in response.reasoning[-1]


async def test_self_check_without_disease_name_gets_no_note(monkeypatch) -> None:
    _patch(monkeypatch, "스트레스 자가진단 설문으로 현재 상태를 점검한다.", _SLEEP, ["record"])

    response = await judge_gate(GateRequest(session_id="unit-test"))

    assert response.verdict == "PASS"
    assert response.medical_purpose_self_check_phrase is None
    assert len(response.reasoning) == 4


async def test_self_check_does_not_hide_an_asserted_medical_purpose(monkeypatch) -> None:
    """자가진단과 함께 치료를 내세우면 치료 표현으로 FAIL이고, 자가진단 안내는 따로 붙이지 않는다."""
    _patch(monkeypatch, "우울증 자가진단 후 맞춤 치료 프로그램을 제공한다.", _SLEEP, ["record"])

    response = await judge_gate(GateRequest(session_id="unit-test"))

    assert response.verdict == "FAIL"
    assert response.medical_purpose_fired is True
    assert "치료" in response.medical_purpose_phrase
    assert response.medical_purpose_self_check_phrase is None


async def test_negated_self_check_is_not_reported_as_self_check(monkeypatch) -> None:
    _patch(monkeypatch, "우울증 자가진단은 제공하지 않고 기분만 기록한다.", _SLEEP, ["record"])

    response = await judge_gate(GateRequest(session_id="unit-test"))

    assert response.verdict == "PASS"
    assert response.medical_purpose_self_check_phrase is None
