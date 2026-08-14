from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.models.reference import CollectionDifficulty, DataDifficulty, SignalConfig
from app.db.models.rule_version import RuleVersion
from app.db.session import AsyncSessionLocal


SIGNAL_CONFIG_ROWS = [
    {"axis": "의료행위표현", "threshold_low": 1, "threshold_mid": 2},
    {"axis": "개인정보민감도", "threshold_low": 1, "threshold_mid": 2},
    {"axis": "광고표현위험", "threshold_low": 1, "threshold_mid": 2},
]

DATA_DIFFICULTY_ROWS = [
    {"data_type": "라이프스타일", "weight": 1},
    {"data_type": "생체지표", "weight": 3},
]

COLLECTION_DIFFICULTY_ROWS = [
    {"method": "수동입력", "weight": 1},
    {"method": "OS연동", "weight": 2},
    {"method": "기기연동", "weight": 4},
    {"method": "기관연동", "weight": 10},
]


async def get_or_create_rule_version(version: str) -> RuleVersion:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(RuleVersion)
            .where(RuleVersion.status == "active")
            .order_by(desc(RuleVersion.activated_at), desc(RuleVersion.created_at))
            .limit(1)
        )
        active_version = result.scalar_one_or_none()
        if active_version:
            return active_version

        seed_version = RuleVersion(version=version, status="active")
        session.add(seed_version)
        await session.commit()
        await session.refresh(seed_version)
        return seed_version


async def upsert_signal_config(rule_version_id) -> int:
    rows = [
        {
            "rule_version_id": rule_version_id,
            **row,
        }
        for row in SIGNAL_CONFIG_ROWS
    ]
    async with AsyncSessionLocal() as session:
        stmt = insert(SignalConfig).values(rows)
        await session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_signal_config_rule_axis",
                set_={
                    "threshold_low": stmt.excluded.threshold_low,
                    "threshold_mid": stmt.excluded.threshold_mid,
                },
            )
        )
        await session.commit()
    return len(rows)


async def upsert_data_difficulty() -> int:
    async with AsyncSessionLocal() as session:
        stmt = insert(DataDifficulty).values(DATA_DIFFICULTY_ROWS)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[DataDifficulty.data_type],
                set_={"weight": stmt.excluded.weight},
            )
        )
        await session.commit()
    return len(DATA_DIFFICULTY_ROWS)


async def upsert_collection_difficulty() -> int:
    async with AsyncSessionLocal() as session:
        stmt = insert(CollectionDifficulty).values(COLLECTION_DIFFICULTY_ROWS)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[CollectionDifficulty.method],
                set_={"weight": stmt.excluded.weight},
            )
        )
        await session.commit()
    return len(COLLECTION_DIFFICULTY_ROWS)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Postgres reference data.")
    parser.add_argument(
        "--seed-rule-version",
        default="v0.reference-seed",
        help="Rule version to create when no active rule_version exists.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned seed counts only.")
    args = parser.parse_args()

    if args.dry_run:
        print(f"signal_config: {len(SIGNAL_CONFIG_ROWS)}")
        print(f"data_difficulty: {len(DATA_DIFFICULTY_ROWS)}")
        print(f"collection_difficulty: {len(COLLECTION_DIFFICULTY_ROWS)}")
        return

    rule_version = await get_or_create_rule_version(args.seed_rule_version)
    signal_count = await upsert_signal_config(rule_version.rule_version_id)
    data_count = await upsert_data_difficulty()
    collection_count = await upsert_collection_difficulty()

    print(f"rule_version_id: {rule_version.rule_version_id}")
    print(f"Imported signal_config: {signal_count}")
    print(f"Imported data_difficulty: {data_count}")
    print(f"Imported collection_difficulty: {collection_count}")


if __name__ == "__main__":
    asyncio.run(main())
