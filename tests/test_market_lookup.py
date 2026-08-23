"""시장현실성·BM추천 공유 조회 전략(app/domain/market_lookup.py) 순수 로직 테스트.

DB 접속이 필요 없다 — relaxation_stages는 SQLAlchemy where절 목록만 조립한다.
"""

from app.db.models import Competitor
from app.domain.market_lookup import CategoryKeys, relaxation_stages


def _levels(keys: CategoryKeys) -> list[str]:
    return [level for level, _ in relaxation_stages(Competitor, keys)]


def test_all_keys_present_yields_three_stages_in_order() -> None:
    keys = CategoryKeys(category_1="수면", category_2="정보제공", target="20대", service_type="앱")
    assert _levels(keys) == ["exact_match", "relaxed_service_type", "relaxed_category_only"]


def test_missing_service_type_skips_exact_match() -> None:
    keys = CategoryKeys(category_1="수면", category_2="정보제공", target="20대", service_type=None)
    assert _levels(keys) == ["relaxed_service_type", "relaxed_category_only"]


def test_missing_target_skips_exact_and_relaxed_service_type() -> None:
    keys = CategoryKeys(category_1="수면", category_2="정보제공", target=None, service_type="앱")
    assert _levels(keys) == ["relaxed_category_only"]


def test_missing_category_axis_yields_no_stages() -> None:
    # category_1/category_2가 없으면(STEP 1 분류가 세션에 반영 안 됨) 어떤 완화 단계도
    # 조회 키가 안 서므로 빈 리스트 — 호출부가 이를 insufficient_data로 처리한다.
    keys = CategoryKeys(category_1="수면", category_2=None, target="20대", service_type="앱")
    assert relaxation_stages(Competitor, keys) == []

    keys = CategoryKeys(category_1=None, category_2=None, target=None, service_type=None)
    assert relaxation_stages(Competitor, keys) == []
