"""app/domain/correction_llm.py 단위 테스트 — DB/네트워크 불필요. 이슈 #58."""

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.redis_client import redis_client
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
    service_description = "약 시간표를 짜드려요"
    cache_key = correction_llm._CACHE_KEY_PREFIX + hashlib.sha256(service_description.encode()).hexdigest()
    try:
        # 캐싱 도입(D-16) 이후 이 테스트가 실제 Redis에 쓴 캐시가 재실행 시 남아있으면
        # AsyncOpenAI 모킹/파싱 로직을 안 타고 캐시값만 반환해 이 테스트의 의미가 없어진다.
        await redis_client.delete(cache_key)
    except Exception:
        pass  # Redis 연결 불가(CI)면 애초에 캐시가 안 걸리니 그냥 진행한다.

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
    try:
        with _patched_client(payload) as mock_openai_cls:
            result = await correction_llm.generate_correction_candidates(service_description)
        mock_openai_cls.assert_called_once()
    finally:
        try:
            await redis_client.delete(cache_key)
        except Exception:
            pass

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


async def test_generate_correction_candidates_uses_cache_on_second_call(monkeypatch) -> None:
    """같은 service_description을 두 번 호출하면 두 번째는 캐시를 써서 OpenAI를 다시 안 부른다(D-16)."""
    monkeypatch.setattr(correction_llm.settings, "openai_api_key", "sk-test")
    service_description = "마음 상태를 짚어드리고 조언해드려요"
    cache_key = correction_llm._CACHE_KEY_PREFIX + hashlib.sha256(service_description.encode()).hexdigest()
    try:
        # 이전 테스트 실행에서 남은 캐시가 있으면 지운다 — Redis가 없는 환경(CI)에서는
        # 이 캐싱 자체가 무의미하니 테스트를 건너뛴다(production 코드는 이미 try/except로
        # Redis 장애를 흡수하지만, 이 테스트는 캐시 동작 자체를 검증하는 게 목적이라 다르다).
        await redis_client.delete(cache_key)
    except Exception:
        pytest.skip("Redis에 연결할 수 없어 캐시 동작을 검증할 수 없습니다.")

    payload = json.dumps(
        {
            "candidates": [
                {
                    "risky_text": "마음 상태를 짚어드려요",
                    "safe_text": "기분 변화를 기록해드려요",
                    "legal_basis": {"document_id": "kr-medical-act-20260407", "article": "제5조"},
                }
            ]
        }
    )
    try:
        with _patched_client(payload) as mock_openai_cls_first:
            first = await correction_llm.generate_correction_candidates(service_description)
        mock_openai_cls_first.assert_called_once()

        with _patched_client(payload) as mock_openai_cls_second:
            second = await correction_llm.generate_correction_candidates(service_description)
        mock_openai_cls_second.assert_not_called()

        assert first == second
    finally:
        await redis_client.delete(cache_key)
