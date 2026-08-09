"""publish()의 rule_version Stage 스코프 회귀 테스트 (구현_현황_정리.md §Stage B).

과거 버그: Stage A만 publish해서 active된 버전이 있는 상태에서 Stage B만 따로 publish하면
`UPDATE rule_versions SET status='deprecated' WHERE status='active'`가 Stage 구분 없이 걸려
Stage A의 active 버전까지 deprecated로 끌려갔다. 수정 후에도 이 스코프가 깨지지 않는지 확인한다.

이번 작업에서 publish.py에 Stage B 신규 필드를 추가했으므로 재확인이 필요한 케이스다.
"""

import pytest
from sqlalchemy import select

from app.db.models import GateKeyword, GateMatrix, RuleVersion
from app.db.session import AsyncSessionLocal
from app.pipeline.nodes.publish import publish

pytestmark = pytest.mark.db

QUOTE = "혈당 수치값을 표시하고 위험 수치일 때 경고 알람을 제공"


def stage_a_draft() -> dict:
    return {
        "stage": "A",
        "fields": {
            "type": "PROHIBITED_ACTION",
            "keyword": "테스트전용키워드",
            "keyword_category": "TREATMENT",
            "data_type_focus": "NONE",
            "verdict": "FAIL_CANDIDATE",
            "weight": 4,
            "legal_basis": {"document_id": "doc-a", "article": "제2조", "quote": QUOTE},
        },
        "legal_basis": {"document_id": "doc-a", "article": "제2조", "quote": QUOTE},
    }


def stage_b_draft() -> dict:
    legal_basis = {"document_id": "doc-b", "article": "IV.3", "quote": QUOTE}
    return {
        "stage": "B",
        "fields": {
            "data_type": "생체지표",
            "function_type": "수치예측·진단",
            "verdict": "FAIL",
            "exemption_note": None,
            "acquire_method": "기기연동",
            "invasive_signal": True,
            "avoidance_redesign": None,
            "avoidance_certification": None,
            "risk_code": None,
            "priority": 3,
            "legal_basis": legal_basis,
        },
        "legal_basis": legal_basis,
    }


async def _active_version_ids(model) -> set:
    async with AsyncSessionLocal() as session:
        return set(
            (
                await session.scalars(
                    select(model.rule_version_id)
                    .distinct()
                    .join(RuleVersion, RuleVersion.rule_version_id == model.rule_version_id)
                    .where(RuleVersion.status == "active")
                )
            ).all()
        )


async def test_stage_b_publish_does_not_deprecate_stage_a_version(restore_db) -> None:
    await publish({"drafts": [stage_a_draft()], "rule_version_id": None})
    stage_a_versions = await _active_version_ids(GateKeyword)
    assert len(stage_a_versions) == 1

    await publish({"drafts": [stage_b_draft()], "rule_version_id": None})

    # Stage B 발행 후에도 Stage A의 active 버전이 그대로 살아 있어야 한다 (버그의 핵심)
    assert await _active_version_ids(GateKeyword) == stage_a_versions
    stage_b_versions = await _active_version_ids(GateMatrix)
    assert len(stage_b_versions) == 1
    assert stage_b_versions.isdisjoint(stage_a_versions), "Stage별로 독립된 lineage여야 한다"


async def test_mixed_batch_creates_independent_versions(restore_db) -> None:
    """같은 publish 호출에 A+B가 섞여도 서로 다른 rule_version을 받는다."""
    await publish({"drafts": [stage_a_draft(), stage_b_draft()], "rule_version_id": None})

    stage_a_versions = await _active_version_ids(GateKeyword)
    stage_b_versions = await _active_version_ids(GateMatrix)
    assert len(stage_a_versions) == 1
    assert len(stage_b_versions) == 1
    assert stage_a_versions.isdisjoint(stage_b_versions)


async def test_stage_b_new_fields_are_persisted(restore_db) -> None:
    """이번에 추가한 5개 컬럼이 실제로 저장되는지 확인한다."""
    await publish({"drafts": [stage_b_draft()], "rule_version_id": None})

    async with AsyncSessionLocal() as session:
        row = await session.scalar(select(GateMatrix).where(GateMatrix.acquire_method.isnot(None)))

    assert row is not None
    assert row.acquire_method == "기기연동"
    assert row.legal_basis_doc == "doc-b"
    assert row.legal_basis_article == "IV.3"
    # D-2 미확정 — 파이프라인은 아직 avoidance_* 문구를 채우지 않는다
    assert row.avoidance_redesign is None
    assert row.avoidance_certification is None
