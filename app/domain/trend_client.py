"""국내 수요 판정 — 검색 트렌드 실시간 조회. 판정엔진_개발설계서.md §8.3.

오프라인에서 이미 계산해둔 `trend_signal_config.trend_slope_threshold`와 같은 방식
(선형회귀 기울기 ÷ 평균값 × 100, %/일)으로, 세션의 category_1에 대응하는 검색어의
최근 1년 기울기를 실시간 계산해 그 임계값과 비교한다. 오프라인 계산과 같은 기간
길이(1년, 일 단위)를 써야 임계값과 비교가 유효하다 — 짧은 기간으로 계산하면
노이즈가 커져 같은 척도로 못 비교한다.

⚠️ 원래 설계(§8.3)는 3단계(급성장/완만/하락)였지만, 실측 임계값이 음수로 나오면서
무너졌다(2026-08-22 확인: 성장 예상군 평균 -0.180%/일 < 하락 예상군 평균
-0.121%/일 — 라벨이 뒤집힌 이상치, 그리고 임계값<0이면 "0 < 기울기 < 임계값"
구간 자체가 성립 불가). DB `trend_signal_config` note 필드에 이미 남겨진 단순화안을
그대로 따라 2단계(상위권/하위권)로 판정한다: 기울기 > 임계값이면 상위권(상대적으로
덜 하락), 아니면 하위권. 이 해석 자체가 팀 재검토 대상이라는 점은 여전히 남아있다.

카테고리 → 검색어 매핑(§15.11 "카테고리 → 검색어 매핑 — 결정 필요")은 팀 검수 전
초안이다(2026-08-24) — CATEGORY_TO_KEYWORD 참고, 실제 서비스 카테고리 감각과
다르면 팀에서 교체해야 한다.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.redis_client import redis_client
from app.db.models import TrendSignalConfig
from app.db.session import AsyncSessionLocal

# §15.11 "카테고리 → 검색어 매핑" — 팀 검수 전 초안(2026-08-24).
CATEGORY_TO_KEYWORD: dict[str, str] = {
    "수면": "수면",
    "정신건강": "정신건강",
    "운동": "운동",
    "식단": "다이어트",
    "만성질환": "만성질환관리",
    "여성건강": "여성건강",
    "유전자": "유전자검사",
    "미용": "뷰티",
}

_LOOKBACK_DAYS = 365  # trend_calc_period(오프라인 계산 기준 1년)와 맞춰야 임계값과
# 비교가 유효하다 — db_구축_설계서.md §6.8 "네이버클라우드플랫폼 Search Trend...
# 2025.08.03~2026.08.03, 일간 단위"와 동일한 기간 길이.
_CACHE_TTL_SECONDS = 24 * 60 * 60  # §8.3 "외부 API 지연·호출한도 대응을 위해 24시간 캐시를 권장"
_CACHE_KEY_PREFIX = "trend_demand:"
# NAVER API HUB(Cloud Platform) 검색어 트렌드 — developers.naver.com의 개인용
# 오픈API(X-Naver-Client-Id/Secret, openapi.naver.com)와는 인증·엔드포인트가 완전히
# 다르다(2026-08-24 확인, api.ncloud-docs.com/docs/naver-api-hub-search-trend).
_NAVER_DATALAB_URL = "https://naverapihub.apigw.ntruss.com/search-trend/v1/search"
_MIN_DATA_POINTS = 30  # 이보다 적으면(API 응답 이상 등) 추세 판정 자체를 포기한다.


class TrendUnavailable(Exception):
    """Naver API 키 미설정, 호출 실패, 임계값 미시딩 등으로 판정 불가할 때.
    market_feasibility 응답에서 domestic_demand만 None으로 빠지고 나머지는 정상 반환된다."""


def _linear_regression_slope(values: list[float]) -> float:
    """최소제곱법 기울기(하루당 변화량). db_구축_설계서.md §6.8 [2단계]와 동일한 방법."""
    n = len(values)
    x_mean = (n - 1) / 2
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


async def _fetch_trend_ratios(keyword: str) -> list[float]:
    if not settings.naver_client_id or not settings.naver_client_secret:
        raise TrendUnavailable("NAVER_CLIENT_ID/NAVER_CLIENT_SECRET이 설정되지 않았습니다.")

    end = date.today() - timedelta(days=1)  # 데이터랩은 오늘 날짜 요청을 거부한다.
    start = end - timedelta(days=_LOOKBACK_DAYS)

    payload = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "timeUnit": "date",
        "keywordGroups": [{"groupName": keyword, "keywords": [keyword]}],
    }
    headers = {
        "X-NCP-APIGW-API-KEY-ID": settings.naver_client_id,
        "X-NCP-APIGW-API-KEY": settings.naver_client_secret,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(_NAVER_DATALAB_URL, json=payload, headers=headers)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise TrendUnavailable(f"네이버 데이터랩 호출 실패: {error}") from error

    body = response.json()
    try:
        ratios = [float(point["ratio"]) for point in body["results"][0]["data"]]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise TrendUnavailable(f"네이버 데이터랩 응답 형식이 예상과 다릅니다: {body}") from error

    if len(ratios) < _MIN_DATA_POINTS:
        raise TrendUnavailable(f"데이터 포인트가 부족합니다({len(ratios)}개).")
    return ratios


async def _load_threshold() -> float:
    # DB 연결 실패·값 파싱 실패도 전부 TrendUnavailable로 통일한다 — 안 그러면
    # assess_domestic_demand()의 except TrendUnavailable을 뚫고 올라가 /feasibility/market
    # 전체가 500으로 죽는다(코드 리뷰로 확인된 실제 버그, 2026-08-25).
    try:
        async with AsyncSessionLocal() as session:
            row = await session.get(TrendSignalConfig, "trend_slope_threshold")
    except SQLAlchemyError as error:
        raise TrendUnavailable(f"trend_signal_config 조회 실패: {error}") from error

    if row is None:
        raise TrendUnavailable("trend_signal_config.trend_slope_threshold가 시딩되지 않았습니다.")
    try:
        return float(row.value)
    except (TypeError, ValueError) as error:
        raise TrendUnavailable(f"trend_slope_threshold 값이 숫자가 아닙니다: {row.value!r}") from error


async def assess_domestic_demand(category_1: str | None) -> str | None:
    """category_1으로 국내 수요(상위권/하위권)를 판정한다. 실패하면 None —
    market_feasibility API가 이 값만 비우고 나머지는 정상 응답한다."""
    if category_1 is None:
        return None
    keyword = CATEGORY_TO_KEYWORD.get(category_1)
    if keyword is None:
        return None

    cache_key = f"{_CACHE_KEY_PREFIX}{keyword}"
    try:
        cached = await redis_client.get(cache_key)
        if cached is not None:
            return json.loads(cached)["domestic_demand"]
    except Exception:
        pass  # 캐시 조회 실패는 치명적이지 않다 — 그냥 다시 계산한다.

    try:
        ratios = await _fetch_trend_ratios(keyword)
        threshold = await _load_threshold()
    except TrendUnavailable:
        return None

    slope = _linear_regression_slope(ratios)
    mean = sum(ratios) / len(ratios)
    if mean == 0:
        return None
    rate = slope / mean * 100  # %/일 — trend_signal_config와 동일한 단위

    demand = "상위권" if rate > threshold else "하위권"

    try:
        await redis_client.set(cache_key, json.dumps({"domestic_demand": demand}), ex=_CACHE_TTL_SECONDS)
    except Exception:
        pass  # 캐시 저장 실패도 치명적이지 않다.

    return demand
