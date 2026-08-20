from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GateKeyword
from app.db.rule_version_queries import ACTIVE_RULE_VERSION_IDS
from app.pipeline.correction_terms import BIOMARKER_EXTRA

SOURCE_TO_ACQUIRE_METHOD = {
    "user_input": "수동입력",
    "device_sync": "기기연동",
    "os_sync": "OS연동",
    "institution_sync": "기관연동",
}


async def load_biomarker_keywords(session: AsyncSession) -> set[str]:
    """생체지표 판별 사전 = gate_keywords(DATA_TYPE) + 보정용 기본 지표."""
    result = await session.execute(
        select(GateKeyword.keyword).where(
            GateKeyword.rule_version_id.in_(ACTIVE_RULE_VERSION_IDS),
            GateKeyword.keyword_category == "DATA_TYPE",
        )
    )
    keywords = {keyword for keyword in result.scalars().all() if keyword}
    return keywords | set(BIOMARKER_EXTRA)


def is_biomarker_name(name: str, biomarker_keywords: set[str]) -> bool:
    return any(keyword in name for keyword in biomarker_keywords)
