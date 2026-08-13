"""누적 발행(B안) 회귀 테스트 — 새 버전이 기존 active 행을 승계하는지 확인한다.

예전에는 이번 draft만 담은 버전을 새로 만들고 기존 active를 내려서, 문서를 한 건씩
투입할 때마다 직전 문서의 룰이 통째로 비활성화됐다(약무 키워드 4행이 그렇게 잠겼다).
"""

import pytest
from sqlalchemy import func, select

from app.db.models import GateKeyword, GateMatrix, RuleVersion
from app.db.session import AsyncSessionLocal
from app.pipeline.nodes.publish import publish

pytestmark = pytest.mark.db

QUOTE = "혈당 수치값을 표시하고 위험 수치일 때 경고 알람을 제공"


def keyword_draft(keyword: str) -> dict:
    legal_basis = {"document_id": "doc-a", "article": "제2조", "quote": QUOTE}
    return {
        "stage": "A",
        "fields": {
            "type": "DISEASE",
            "keyword": keyword,
            "keyword_category": "DATA_TYPE",
            "data_type_focus": "NUMERIC",
            "verdict": "CONTEXT_CHECK",
            "weight": 2,
            "legal_basis": legal_basis,
        },
        "legal_basis": legal_basis,
    }


async def _active_keywords() -> set[str]:
    async with AsyncSessionLocal() as session:
        return set(
            (
                await session.scalars(
                    select(GateKeyword.keyword)
                    .join(RuleVersion, RuleVersion.rule_version_id == GateKeyword.rule_version_id)
                    .where(RuleVersion.status == "active")
                )
            ).all()
        )


async def _active_version_count(model) -> int:
    async with AsyncSessionLocal() as session:
        return len(
            set(
                (
                    await session.scalars(
                        select(model.rule_version_id)
                        .distinct()
                        .join(RuleVersion, RuleVersion.rule_version_id == model.rule_version_id)
                        .where(RuleVersion.status == "active")
                    )
                ).all()
            )
        )


async def test_second_publish_inherits_first_batch(restore_db) -> None:
    """2회차 발행 후에도 1회차 키워드가 active에 남아 있어야 한다 (B안의 핵심)."""
    await publish({"drafts": [keyword_draft("테스트키워드1")], "rule_version_id": None})
    assert "테스트키워드1" in await _active_keywords()

    await publish({"drafts": [keyword_draft("테스트키워드2")], "rule_version_id": None})

    active = await _active_keywords()
    assert "테스트키워드1" in active, "직전 발행분이 승계되지 않고 잠겼다"
    assert "테스트키워드2" in active


async def test_active_version_stays_unique_per_stage(restore_db) -> None:
    """누적 발행이어도 Stage당 active 버전은 유일해야 한다 — 조회 쪽 불변식."""
    await publish({"drafts": [keyword_draft("테스트키워드1")], "rule_version_id": None})
    await publish({"drafts": [keyword_draft("테스트키워드2")], "rule_version_id": None})
    await publish({"drafts": [keyword_draft("테스트키워드3")], "rule_version_id": None})

    assert await _active_version_count(GateKeyword) == 1


async def test_inheritance_does_not_leak_across_stages(restore_db) -> None:
    """Stage A 발행이 Stage B 행을 끌어오거나 B의 active를 내리면 안 된다."""
    matrix_legal_basis = {"document_id": "doc-b", "article": "IV.3", "quote": QUOTE}
    matrix_draft = {
        "stage": "B",
        "fields": {
            "data_type": "생체지표",
            "function_type": "수치예측·진단",
            "verdict": "FAIL",
            "exemption_note": None,
            "acquire_method": None,
            "invasive_signal": False,
            "invasive_keyword_hit": False,
            "avoidance_redesign": None,
            "avoidance_certification": None,
            "risk_code": None,
            "priority": 3,
            "legal_basis": matrix_legal_basis,
        },
        "legal_basis": matrix_legal_basis,
    }
    await publish({"drafts": [matrix_draft], "rule_version_id": None})
    matrix_before = await _active_version_count(GateMatrix)

    await publish({"drafts": [keyword_draft("테스트키워드1")], "rule_version_id": None})

    assert await _active_version_count(GateMatrix) == matrix_before == 1
    async with AsyncSessionLocal() as session:
        active_matrix_rows = await session.scalar(
            select(func.count())
            .select_from(GateMatrix)
            .join(RuleVersion, RuleVersion.rule_version_id == GateMatrix.rule_version_id)
            .where(RuleVersion.status == "active")
        )
    assert active_matrix_rows >= 1, "Stage A 발행이 Stage B의 active 행을 날렸다"
