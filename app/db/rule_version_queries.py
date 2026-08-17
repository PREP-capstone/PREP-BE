"""여러 곳(API 판정 엔진, 오프라인 파이프라인)이 공유하는 "활성 rule_version_id" 조회."""

import uuid

from sqlalchemy import select

from app.db.models import RuleVersion
from app.db.session import AsyncSessionLocal

ACTIVE_RULE_VERSION_IDS = (
    select(RuleVersion.rule_version_id).where(RuleVersion.status == "active").scalar_subquery()
)


async def resolve_active_rule_version_ids() -> list[uuid.UUID]:
    """활성 rule_version_id를 한 번만 확정해서 반환한다.

    한 요청 안에서 여러 쿼리(gate_keywords, correction_rules, signal_config 등)가
    각자 ACTIVE_RULE_VERSION_IDS 서브쿼리로 "활성" 여부를 다시 판단하면, 그 사이에
    publish()가 커밋될 경우 쿼리마다 서로 다른 버전을 기준으로 스냅샷을 떠서
    (예: matched_keywords는 구버전, correction_rules는 신버전) 매칭이 조용히
    어긋날 수 있다. 여러 쿼리가 같은 스냅샷을 봐야 하는 호출부는 이 함수로 한 번
    확정한 rule_version_id 목록을 모든 쿼리에 그대로 넘겨써야 한다.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(RuleVersion.rule_version_id).where(RuleVersion.status == "active"))
        return list(result.scalars().all())
