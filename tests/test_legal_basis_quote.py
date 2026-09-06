"""_fill_quotes 단위 테스트 — RAG 원문(quote) 연결 화이트리스트(이슈 #39, #93)."""

from types import SimpleNamespace

import app.api.judgement as judgement
from app.api.judgement import CorrectionMatch, _fill_quotes
from app.schemas.common import LegalBasis


def match(document_id: str, article: str) -> CorrectionMatch:
    return CorrectionMatch(
        risky_text="x",
        safe_text="y",
        regulatory_score=0,
        advertising_score=0,
        legal_basis=LegalBasis(document_id=document_id, article=article),
        exact_phrase_match=True,
        match_source="rule",
    )


async def test_whitelisted_document_gets_real_quote(monkeypatch) -> None:
    async def fake_lookup(request):
        return SimpleNamespace(
            result=[
                SimpleNamespace(
                    section_id="제24조",
                    chunk_text="약사는 복약지도에 필요한 사항을 환자에게 설명해야 한다.",
                )
            ]
        )

    monkeypatch.setattr(judgement, "lookup_rag_chunks", fake_lookup)

    m = match("kr-pharmaceutical-affairs-act-20260621", "제24조")
    await _fill_quotes([m])
    assert m.legal_basis.quote is not None
    assert "복약지도" in m.legal_basis.quote
    assert m.legal_basis.quote_status == "FOUND"
    assert m.legal_basis.quote_message is None


async def test_non_whitelisted_document_stays_none(monkeypatch) -> None:
    async def fake_lookup(request):
        raise AssertionError("화이트리스트 밖 문서는 RAG 조회를 호출하면 안 된다.")

    monkeypatch.setattr(judgement, "lookup_rag_chunks", fake_lookup)

    m = match("kr-unverified-guide", "II")
    await _fill_quotes([m])
    assert m.legal_basis.quote is None
    assert m.legal_basis.quote_status == "UNTRUSTED_DOCUMENT"
    assert "검증되지 않아" in m.legal_basis.quote_message


async def test_nonmedical_2022_document_gets_real_quote(monkeypatch) -> None:
    async def fake_lookup(request):
        assert request.document_id == "kr-mohw-nonmedical-health-guide-202209"
        assert request.section_ids == ["II.3"]
        return SimpleNamespace(
            result=[
                SimpleNamespace(
                    section_id="II.3",
                    chunk_text="의료행위 판단 기준에 따라 비의료기관의 건강관리서비스 범위를 검토한다.",
                )
            ]
        )

    monkeypatch.setattr(judgement, "lookup_rag_chunks", fake_lookup)

    m = match("kr-mohw-nonmedical-health-guide-202209", "II.3")
    await _fill_quotes([m])
    assert m.legal_basis.quote is not None
    assert "의료행위 판단 기준" in m.legal_basis.quote
    assert m.legal_basis.quote_status == "FOUND"
    assert m.legal_basis.quote_message is None


async def test_whitelisted_document_missing_chunk_stays_none(monkeypatch) -> None:
    """약사법 제44조는 화이트리스트 문서 안이지만 아직 미청킹 — 에러 없이 quote만 None."""
    async def fake_lookup(request):
        return SimpleNamespace(result=[])

    monkeypatch.setattr(judgement, "lookup_rag_chunks", fake_lookup)

    m = match("kr-pharmaceutical-affairs-act-20260621", "제44조")
    await _fill_quotes([m])
    assert m.legal_basis.quote is None
    assert m.legal_basis.quote_status == "MISSING_CHUNK"
    assert "section_id" in m.legal_basis.quote_message


async def test_whitelisted_document_lookup_failure_stays_none(monkeypatch) -> None:
    async def fake_lookup(request):
        raise RuntimeError("rag unavailable")

    monkeypatch.setattr(judgement, "lookup_rag_chunks", fake_lookup)

    m = match("kr-pharmaceutical-affairs-act-20260621", "제24조")
    await _fill_quotes([m])
    assert m.legal_basis.quote is None
    assert m.legal_basis.quote_status == "LOOKUP_FAILED"
    assert "오류" in m.legal_basis.quote_message
