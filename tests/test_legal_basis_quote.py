"""_fill_quotes 골든테스트 — RAG 원문(quote) 연결 화이트리스트(이슈 #39).

data_sensitivity 테스트와 같은 이유로 실 RDS 데이터 대상, 쓰기 없이 읽기만 한다.
문서/조문 값은 실제 seed 데이터(correction_rules·evidence_chunks)에 맞춰져 있다 —
시드가 바뀌면 이 테스트도 같이 깨져야 한다.
"""

import pytest

from app.api.judgement import CorrectionMatch, _fill_quotes
from app.schemas.common import LegalBasis

pytestmark = pytest.mark.db


def match(document_id: str, article: str) -> CorrectionMatch:
    return CorrectionMatch(
        risky_text="x",
        safe_text="y",
        regulatory_score=0,
        advertising_score=0,
        legal_basis=LegalBasis(document_id=document_id, article=article),
        exact_phrase_match=True,
    )


async def test_whitelisted_document_gets_real_quote() -> None:
    m = match("kr-pharmaceutical-affairs-act-20260621", "제24조")
    await _fill_quotes([m])
    assert m.legal_basis.quote is not None
    assert "복약지도" in m.legal_basis.quote


async def test_non_whitelisted_document_stays_none() -> None:
    """비의료 건강관리서비스 가이드라인은 판본 불일치(룰베이스_RAG_정합성_추적표.md 표1)라 화이트리스트 밖."""
    m = match("kr-mohw-nonmedical-health-guide-202209", "II")
    await _fill_quotes([m])
    assert m.legal_basis.quote is None


async def test_whitelisted_document_missing_chunk_stays_none() -> None:
    """약사법 제44조는 화이트리스트 문서 안이지만 아직 미청킹 — 에러 없이 quote만 None."""
    m = match("kr-pharmaceutical-affairs-act-20260621", "제44조")
    await _fill_quotes([m])
    assert m.legal_basis.quote is None
