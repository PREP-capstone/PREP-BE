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

    D-12(derived_from_keyword_id 재연결, publish.py) 이후로는 CorrectionRule.
    derived_from_keyword_id도 함께 스냅샷·복원해야 한다 — Stage A publish()는 "테스트가
    만든" 키워드뿐 아니라 **그 시점의 active 키워드 전체**를 승계 복제하고, 기존
    correction_rules(테스트 밖에서 실제로 쌓인 데이터 포함)의 FK를 새로 생긴 사본으로
    재연결한다. FK 값을 원래대로 되돌리지 않고 새로 생긴 GateKeyword 행을 먼저 지우면
    "아직 참조 중인 행을 지운다"는 FK 위반이 난다.
    """
    async with AsyncSessionLocal() as session:
        before_rows = {
            model.__tablename__: set((await session.scalars(select(pk))).all())
            for model, pk in _RULE_TABLES
        }
        before_derived = dict(
            (
                await session.execute(
                    select(CorrectionRule.rule_id, CorrectionRule.derived_from_keyword_id)
                )
            ).all()
        )
        before_versions = {
            row[0]: row[1]
            for row in (
                await session.execute(select(RuleVersion.rule_version_id, RuleVersion.status))
            ).all()
        }

    yield

    async with AsyncSessionLocal() as session:
        # 새로 생긴 CorrectionRule부터 지운다 — 남기는 기존 행이 새 GateKeyword를
        # 참조하고 있어도, 아래에서 FK 값을 원복하면 문제가 없어진다.
        keep_correction = before_rows[CorrectionRule.__tablename__]
        if keep_correction:
            await session.execute(delete(CorrectionRule).where(CorrectionRule.rule_id.notin_(keep_correction)))
        else:
            await session.execute(delete(CorrectionRule))

        # 재연결로 바뀐 FK 값을 원래대로 되돌린다.
        for rule_id, original_keyword_id in before_derived.items():
            await session.execute(
                update(CorrectionRule)
                .where(CorrectionRule.rule_id == rule_id)
                .values(derived_from_keyword_id=original_keyword_id)
            )

        for model, pk in _RULE_TABLES:
            if model is CorrectionRule:
                continue  # 위에서 이미 처리
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
