"""app/domain/correction_llm.py 단위 테스트 — DB/네트워크 불필요. 이슈 #58."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain import correction_llm


def _fake_response(content: str):
    message = MagicMock(content=content)
    choice = MagicMock(message=message)
    return MagicMock(choices=[choice])


def _patched_client(response_content: str):
    """settings.openai_api_key를 채워 _build_client()를 통과시키고, AsyncOpenAI()가
    반환할 client.chat.completions.create()를 고정된 응답으로 모킹한다."""
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_fake_response(response_content))
    return patch("app.domain.correction_llm.AsyncOpenAI", return_value=mock_client)


async def test_generate_correction_candidates_raises_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(correction_llm.settings, "openai_api_key", "")
    with pytest.raises(correction_llm.LLMUnavailable):
        await correction_llm.generate_correction_candidates("아무 문장")


async def test_generate_correction_candidates_parses_and_normalizes_article(monkeypatch) -> None:
    monkeypatch.setattr(correction_llm.settings, "openai_api_key", "sk-test")
    payload = json.dumps(
        {
            "candidates": [
                {
                    "risky_text": "약 시간표를 짜드려요",
                    "safe_text": "복약 알림을 보내드려요",
                    "legal_basis": {
                        "document_id": "kr-pharmaceutical-affairs-act-20260621",
                        # 장 접두어가 섞인 표기 — normalize_article()이 벗겨내는지 같이 확인.
                        "article": "제1장.제5조",
                    },
                }
            ]
        }
    )
    with _patched_client(payload):
        result = await correction_llm.generate_correction_candidates("약 시간표를 짜드려요")

    assert result == [
        {
            "risky_text": "약 시간표를 짜드려요",
            "safe_text": "복약 알림을 보내드려요",
            "legal_basis": {"document_id": "kr-pharmaceutical-affairs-act-20260621", "article": "제5조"},
        }
    ]


async def test_generate_correction_candidates_raises_on_malformed_json(monkeypatch) -> None:
    monkeypatch.setattr(correction_llm.settings, "openai_api_key", "sk-test")
    with _patched_client("이건 JSON이 아님"):
        with pytest.raises(correction_llm.LLMUnavailable):
            await correction_llm.generate_correction_candidates("아무 문장")


async def test_generate_correction_candidates_raises_on_missing_expected_key(monkeypatch) -> None:
    """strict json_schema가 candidates 키를 보장하지만, 방어적으로 KeyError도 잡는지 확인."""
    monkeypatch.setattr(correction_llm.settings, "openai_api_key", "sk-test")
    with _patched_client(json.dumps({"unexpected_key": []})):
        with pytest.raises(correction_llm.LLMUnavailable):
            await correction_llm.generate_correction_candidates("아무 문장")
