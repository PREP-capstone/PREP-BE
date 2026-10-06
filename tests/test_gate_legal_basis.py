"""GATE 응답 근거 조문(legal_basis) 단위 테스트 — 판정엔진_개발설계서.md §10.5.

judge_gate의 DB 의존 3곳(세션 조회·생체지표 사전·RAG 원문 조회)을 모킹해 DB 없이 돈다.
실제 세션·DB 경로는 test_judgement_session.py(@pytest.mark.db)가 따로 확인한다.
"""

from types import SimpleNamespace

import app.api.judgement as judgement
from app.api.judgement import GateRequest, judge_gate
from app.pipeline.gate_matrix_table import LLM_GUIDE_DOCUMENT_ID, WELLNESS_DOCUMENT_ID
from app.schemas.common import HealthDataItemInput


def _patch_session(monkeypatch, description: str, items: list[HealthDataItemInput], actions: list[str]) -> None:
    async def fake_load_session(session_id: str):
        return SimpleNamespace(service_description=description, service_actions=actions), items

    async def fake_biomarker_keywords(session) -> set[str]:
        return {"심박수", "혈당"}

    monkeypatch.setattr(judgement, "_load_session", fake_load_session)
    monkeypatch.setattr(judgement, "load_biomarker_keywords", fake_biomarker_keywords)


def _patch_rag(monkeypatch, chunks: dict[str, str], calls: list) -> None:
    async def fake_lookup(request):
        calls.append(request)
        return SimpleNamespace(
            result=[
                SimpleNamespace(section_id=section_id, chunk_text=text)
                for section_id, text in chunks.items()
                if section_id in request.section_ids
            ]
        )

    monkeypatch.setattr(judgement, "lookup_rag_chunks", fake_lookup)


async def test_matrix_fail_cites_wellness_iv3_with_quote(monkeypatch) -> None:
    """혈당 수치 표시 + 위험 알람 = (생체지표, 수치예측·진단) FAIL → 근거는 웰니스 판단기준 IV.3."""
    _patch_session(
        monkeypatch,
        "혈당 수치를 표시하고 위험 수치일 때 경고 알람을 보낸다.",
        [HealthDataItemInput(name="혈당", data_type="numeric", unit="mg/dL", source="user_input")],
        ["alert"],
    )
    _patch_rag(monkeypatch, {"IV.3": "3. 개인용 건강관리제품과 의료기기 판단 사례 ..."}, [])

    response = await judge_gate(GateRequest(session_id="unit-test"))

    assert response.verdict == "FAIL"
    assert response.hardcheck_fired is False
    assert response.legal_basis.document_id == WELLNESS_DOCUMENT_ID
    assert response.legal_basis.article == "IV.3"
    assert response.legal_basis.title is not None
    assert response.legal_basis.quote_status == "FOUND"
    assert "판단 사례" in response.legal_basis.quote


async def test_hardcheck_fail_cites_high_risk_rule_not_matrix_cell(monkeypatch) -> None:
    """하드체크 FAIL은 매트릭스를 거치지 않으므로 근거도 매트릭스 칸이 아니라 고위해도 판정 규정
    (III.2.나)이어야 한다 — function_type=단순기록이라 매트릭스로 보면 PASS 칸(IV.1.가)이다."""
    _patch_session(
        monkeypatch,
        "CGM 연속혈당측정기와 연동해 심박수를 실시간으로 기록한다.",
        [HealthDataItemInput(name="심박수", data_type="numeric", unit="bpm", source="device_sync")],
        ["record"],
    )
    _patch_rag(monkeypatch, {"III.2.나": "나 고위해도 ○ ... 침습적인 경우 ..."}, [])

    response = await judge_gate(GateRequest(session_id="unit-test"))

    assert response.hardcheck_fired is True
    assert response.legal_basis.document_id == WELLNESS_DOCUMENT_ID
    assert response.legal_basis.article == "III.2.나"
    assert response.legal_basis.quote_status == "FOUND"


async def test_untrusted_guide_basis_skips_rag_lookup(monkeypatch) -> None:
    """(라이프스타일, 수치예측·진단) CONDITIONAL의 근거인 LLM 가이드라인은 RAG 화이트리스트 밖이라
    원문 조회 없이 UNTRUSTED_DOCUMENT로 내려가야 한다 — 판본이 검증 안 된 원문을 보여주지 않는다."""
    _patch_session(
        monkeypatch,
        "걸음수 기록으로 다음 주 활동량을 예측한다.",
        [HealthDataItemInput(name="걸음수", data_type="numeric", unit="걸음", source="os_sync")],
        ["predict"],
    )
    calls: list = []
    _patch_rag(monkeypatch, {}, calls)

    response = await judge_gate(GateRequest(session_id="unit-test"))

    assert response.verdict == "CONDITIONAL"
    assert response.legal_basis.document_id == LLM_GUIDE_DOCUMENT_ID
    assert response.legal_basis.quote is None
    assert response.legal_basis.quote_status == "UNTRUSTED_DOCUMENT"
    assert calls == []


async def test_rag_failure_keeps_verdict_and_marks_lookup_failed(monkeypatch) -> None:
    """RAG 장애는 판정을 바꾸지 않는다(§10.1) — quote만 비고 LOOKUP_FAILED로 사유를 알린다."""
    _patch_session(
        monkeypatch,
        "사용자가 측정한 심박수를 기록하고 히스토리로 조회한다.",
        [HealthDataItemInput(name="심박수", data_type="numeric", unit="bpm", source="user_input")],
        ["record"],
    )

    async def failing_lookup(request):
        raise RuntimeError("RAG down")

    monkeypatch.setattr(judgement, "lookup_rag_chunks", failing_lookup)

    response = await judge_gate(GateRequest(session_id="unit-test"))

    assert response.verdict == "PASS"
    assert response.legal_basis.article == "IV.1.가"
    assert response.legal_basis.quote is None
    assert response.legal_basis.quote_status == "LOOKUP_FAILED"
