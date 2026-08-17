"""여러 곳(API 판정 엔진, 오프라인 파이프라인)이 공유하는 "활성 rule_version_id" 서브쿼리."""

from sqlalchemy import select

from app.db.models import RuleVersion

ACTIVE_RULE_VERSION_IDS = (
    select(RuleVersion.rule_version_id).where(RuleVersion.status == "active").scalar_subquery()
)
