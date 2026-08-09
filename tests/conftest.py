import sys
from pathlib import Path

import pytest
from sqlalchemy import delete, select, update

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.models import CorrectionRule, GateKeyword, GateMatrix, RuleVersion
from app.db.session import AsyncSessionLocal, engine

_RULE_TABLES = (
    (GateKeyword, GateKeyword.keyword_id),
    (GateMatrix, GateMatrix.matrix_id),
    (CorrectionRule, CorrectionRule.rule_id),
)


@pytest.fixture(scope="session", autouse=True)
async def dispose_engine():
    """세션이 끝날 때 커넥션 풀을 정리한다 — 루프가 닫힌 뒤 정리되면 예외가 난다."""
    yield
    await engine.dispose()


@pytest.fixture
async def restore_db():
    """테스트가 만든 룰 row·rule_version을 지우고 기존 상태를 되돌린다.

    publish()는 자체 세션에서 커밋하므로 트랜잭션 롤백으로 감쌀 수 없다. 대신 테스트 전
    스냅샷을 떠 두고, 끝난 뒤 신규 row를 삭제하고 rule_versions.status를 원래대로 돌린다.
    이렇게 하지 않으면 테스트가 시드 데이터의 active 버전을 deprecated로 끌고 간다.
    """
    async with AsyncSessionLocal() as session:
        before_rows = {
            model.__tablename__: set((await session.scalars(select(pk))).all())
            for model, pk in _RULE_TABLES
        }
        before_versions = {
            row[0]: row[1]
            for row in (
                await session.execute(select(RuleVersion.rule_version_id, RuleVersion.status))
            ).all()
        }

    yield

    async with AsyncSessionLocal() as session:
        for model, pk in _RULE_TABLES:
            keep = before_rows[model.__tablename__]
            if keep:
                await session.execute(delete(model).where(pk.notin_(keep)))
            else:
                await session.execute(delete(model))

        await session.execute(
            delete(RuleVersion).where(RuleVersion.rule_version_id.notin_(before_versions))
            if before_versions
            else delete(RuleVersion)
        )
        for version_id, status in before_versions.items():
            await session.execute(
                update(RuleVersion)
                .where(RuleVersion.rule_version_id == version_id)
                .values(status=status)
            )
        await session.commit()
