"""시장현실성(§03)·BM추천(§04) 공유 조회 전략.

판정엔진_개발설계서.md §8.2 / db_구축_설계서.md §6.4: competitors·bm_mapping 둘 다
category_1 + category_2 + target + service_type 4키로 조회하되, 4키를 전부 맞춰
세면 시드 규모(competitors 101건)로는 대부분 n<=2가 나와 무조건 Opportunity가
되므로 아래 순서로 완화한다.

    1) exact_match          : 4키 전부 일치
    2) relaxed_service_type : service_type 조건 해제
    3) relaxed_category_only: category_1 + category_2만 일치
    4) insufficient_data    : 위 3단계 모두 매칭 0건 (또는 애초에 category_1/category_2가 없음)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MatchLevel = Literal["exact_match", "relaxed_service_type", "relaxed_category_only", "insufficient_data"]


@dataclass(frozen=True)
class CategoryKeys:
    category_1: str | None
    category_2: str | None
    target: str | None
    service_type: str | None

_MATCH_LEVEL_DESCRIPTIONS: dict[MatchLevel, str] = {
    "exact_match": "카테고리, 세부 기능, 타깃, 서비스 형태가 모두 같은 선례를 기준으로 비교했습니다.",
    "relaxed_service_type": "서비스 형태는 제외하고 카테고리, 세부 기능, 타깃이 같은 선례를 기준으로 비교했습니다.",
    "relaxed_category_only": "타깃과 서비스 형태는 제외하고 카테고리와 세부 기능이 같은 선례를 기준으로 비교했습니다.",
    "insufficient_data": "카테고리 정보가 부족하거나 비교 가능한 선례가 아직 충분하지 않습니다.",
}


def describe_match_level(match_level: MatchLevel) -> str:
    return _MATCH_LEVEL_DESCRIPTIONS[match_level]


def relaxation_stages(model, keys: CategoryKeys) -> list[tuple[MatchLevel, list]]:
    """시도할 (match_level, SQLAlchemy where절 목록) 목록을 완화 순서대로 반환한다.

    category_1/category_2 자체가 없으면(STEP 1 분류 미반영 세션) 어떤 단계도 조회 키가
    안 서므로 빈 리스트를 반환한다 — 호출부는 빈 리스트를 insufficient_data로 처리한다.
    target/service_type이 개별적으로 없는 경우는 그 값을 요구하는 단계만 건너뛴다.
    """
    if not (keys.category_1 and keys.category_2):
        return []

    stages: list[tuple[MatchLevel, list]] = []
    base = [model.category_1 == keys.category_1, model.category_2 == keys.category_2]

    if keys.target and keys.service_type:
        stages.append((
            "exact_match",
            [*base, model.target == keys.target, model.service_type == keys.service_type],
        ))
    if keys.target:
        stages.append(("relaxed_service_type", [*base, model.target == keys.target]))
    stages.append(("relaxed_category_only", base))
    return stages
