"""국내 수요(검색 트렌드) 판정 회귀 테스트. 판정엔진_개발설계서.md §8.3.

실제 NAVER API HUB 호출이 필요한 케이스는 @pytest.mark.naver로 표시한다(호출
한도 소모) — `-m "not naver"`로 제외 가능(CI 기본값). DB(trend_signal_config
임계값 조회)도 함께 필요해 db 마커도 같이 붙인다.
"""

import pytest

from app.domain import trend_client
from app.domain.trend_client import CATEGORY_TO_KEYWORD, _linear_regression_slope, assess_domestic_demand


def test_category_to_keyword_covers_all_eight_category_1_labels() -> None:
    # category_classifier.CATEGORY_1_LABELS와 키 집합이 정확히 일치해야 한다 —
    # 하나라도 빠지면 그 카테고리는 조용히 domestic_demand=None으로만 나온다.
    from app.domain.category_classifier import CATEGORY_1_LABELS

    assert set(CATEGORY_TO_KEYWORD.keys()) == set(CATEGORY_1_LABELS)


def test_linear_regression_slope_of_constant_series_is_zero() -> None:
    assert _linear_regression_slope([50.0] * 10) == 0.0


def test_linear_regression_slope_of_linear_increase() -> None:
    # y = 2x + 상수 형태 — 기울기가 정확히 2로 나와야 한다.
    values = [10.0 + 2.0 * i for i in range(20)]
    assert _linear_regression_slope(values) == pytest.approx(2.0)


def test_linear_regression_slope_of_linear_decrease() -> None:
    values = [100.0 - 1.5 * i for i in range(20)]
    assert _linear_regression_slope(values) == pytest.approx(-1.5)


async def test_assess_domestic_demand_returns_none_for_unmapped_category() -> None:
    assert await assess_domestic_demand(None) is None
    assert await assess_domestic_demand("존재하지-않는-카테고리") is None


async def test_assess_domestic_demand_returns_none_without_naver_credentials(monkeypatch) -> None:
    # "운동"은 다른 테스트에서 이미 캐시됐을 수 있어 캐시 우선 조회를 건드리지
    # 않는 카테고리(유전자)로 확인한다 — 캐시 히트가 나면 자격증명 체크 자체를
    # 못 거치고 통과해버려 이 테스트의 의미가 없어진다.
    monkeypatch.setattr(trend_client.settings, "naver_client_id", "")
    monkeypatch.setattr(trend_client.settings, "naver_client_secret", "")
    assert await assess_domestic_demand("유전자") is None


@pytest.mark.naver
@pytest.mark.db
async def test_assess_domestic_demand_real_call_returns_valid_tier() -> None:
    demand = await assess_domestic_demand("운동")
    assert demand in ("상위권", "하위권")
