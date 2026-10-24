"""아이디어 검진 결과의 짧은 수명 Redis 캐시.

PDF 다운로드 시 /analysis/evaluate를 다시 실행하면 LLM 서술이 달라지거나 지연이 생길 수
있다. 그래서 성공한 평가 결과만 Redis에 잠시 두고, 만료 후에는 복구하지 않는다.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import settings
from app.core.redis_client import redis_client

logger = logging.getLogger(__name__)
_CACHE_PREFIX = "analysis_report:"


def _key(session_id: str) -> str:
    return _CACHE_PREFIX + session_id


async def cache_analysis_result(session_id: str, result: dict[str, Any]) -> None:
    """평가 API의 성공 응답을 임시 보관한다.

    캐시 장애가 검진 자체를 실패시키면 안 되므로 다운로드만 나중에 409가 되게 하고,
    평가 결과 응답은 그대로 반환한다.
    """
    try:
        await redis_client.set(
            _key(session_id),
            json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            ex=settings.report_result_ttl_seconds,
        )
    except Exception:  # Redis 연결 장애는 이 API의 판정 성공 여부와 별개다.
        logger.warning("Failed to cache analysis report result", exc_info=True)


async def load_analysis_result(session_id: str) -> dict[str, Any] | None:
    try:
        value = await redis_client.get(_key(session_id))
    except Exception:
        logger.warning("Failed to load cached analysis report result", exc_info=True)
        return None
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        logger.warning("Discarding malformed cached analysis report result")
        return None
