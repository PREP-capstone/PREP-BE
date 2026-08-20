"""_match_privacy_score 골든테스트 — item_label 부분매칭 → item_code PK 매칭 전환(작업 #6 방향 B).

data_sensitivity는 2번 담당 소유 시드 테이블이라 여기서는 쓰기 없이 읽기만 한다
(CLAUDE.md). 시드된 item_code·sensitivity_level 조합(lifestyle_*=1, sensitive_*=3)에
의존한다 — 시드가 바뀌면 이 테스트도 같이 깨져야 한다.
"""

import pytest

from app.api.judgement import _match_privacy_score
from app.schemas.common import HealthDataItemInput

pytestmark = pytest.mark.db


def item(item_code: str | None) -> HealthDataItemInput:
    return HealthDataItemInput(name="x", data_type="text", source="user_input", item_code=item_code)


async def test_adopts_max_sensitivity_level_among_items() -> None:
    items = [item("lifestyle_001"), item("sensitive_001")]
    assert await _match_privacy_score(items) == 3


async def test_unknown_item_code_contributes_zero_silently() -> None:
    items = [item("lifestyle_001"), item("no_such_item_code")]
    assert await _match_privacy_score(items) == 1


async def test_all_item_codes_none_returns_zero() -> None:
    items = [item(None), item(None)]
    assert await _match_privacy_score(items) == 0
