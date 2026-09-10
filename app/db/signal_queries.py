import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.db.models import SignalConfig
from app.db.session import AsyncSessionLocal


async def signal_thresholds(rule_version_ids: list[uuid.UUID]) -> dict[str, tuple[int, int]]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(SignalConfig).where(SignalConfig.rule_version_id.in_(rule_version_ids))
            )
        ).scalars().all()
    thresholds: dict[str, tuple[int, int]] = {}
    for row in rows:
        if row.axis in thresholds:
            raise HTTPException(
                status_code=500,
                detail=f"signal_config에 축 '{row.axis}'의 활성 임계값이 중복됩니다",
            )
        thresholds[row.axis] = (row.threshold_low, row.threshold_mid)
    return thresholds
