"""검수 결정 API의 status 생명주기 회귀 테스트 (pending → resolving → resolved).

두 가지를 막기 위한 상태다(2026-09-27 자체리뷰).
- 동시에 들어온 제출 두 건이 모두 통과해 같은 배치를 두 번 publish하는 것
- publish가 실패했을 때 resolved로 남아 재제출이 409로 막히고 스레드가 고착되는 것
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

import app.api.rule_documents as rule_documents
from app.api.rule_documents import DecisionItem, RuleDraftDecisionRequest, decide_rule_draft
from app.db.models import RuleReviewQueue
from app.db.session import AsyncSessionLocal

pytestmark = pytest.mark.db


async def _seed_pending(thread_id: str) -> None:
    async with AsyncSessionLocal() as session:
        session.add(
            RuleReviewQueue(
                thread_id=thread_id,
                document_id="test-decision-doc",
                items=[{"draft": {"stage": "A"}, "status": "auto_passed", "reasons": []}],
                chunks=[],
                status="pending",
            )
        )
        await session.commit()


async def _status(thread_id: str) -> str:
    async with AsyncSessionLocal() as session:
        row = await session.get(RuleReviewQueue, thread_id)
        return row.status


async def _cleanup(thread_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(RuleReviewQueue).where(RuleReviewQueue.thread_id == thread_id))
        await session.commit()


def _request() -> RuleDraftDecisionRequest:
    return RuleDraftDecisionRequest(decisions=[DecisionItem(action="approve")])


def _graph(ainvoke: AsyncMock):
    graph = type("FakeGraph", (), {})()
    graph.ainvoke = ainvoke
    return graph


async def test_decision_marks_resolved_on_success() -> None:
    thread_id = str(uuid.uuid4())
    await _seed_pending(thread_id)
    try:
        with (
            patch.object(rule_documents, "get_checkpointer", lambda: None),
            patch.object(rule_documents, "build_graph", lambda checkpointer=None: _graph(AsyncMock())),
        ):
            result = await decide_rule_draft(thread_id, _request(), reviewer="tester")
        assert result.status == "resolved"
        assert await _status(thread_id) == "resolved"
    finally:
        await _cleanup(thread_id)


async def test_decision_reverts_to_pending_when_graph_fails() -> None:
    """publish 실패 등으로 그래프가 죽으면 다시 제출할 수 있어야 한다 — resolved로 남기면
    409에 막혀 DB를 손으로 고치지 않고는 그 배치를 살릴 방법이 없다."""
    thread_id = str(uuid.uuid4())
    await _seed_pending(thread_id)
    try:
        failing = AsyncMock(side_effect=RuntimeError("publish 실패"))
        with (
            patch.object(rule_documents, "get_checkpointer", lambda: None),
            patch.object(rule_documents, "build_graph", lambda checkpointer=None: _graph(failing)),
            pytest.raises(RuntimeError),
        ):
            await decide_rule_draft(thread_id, _request(), reviewer="tester")
        assert await _status(thread_id) == "pending"
    finally:
        await _cleanup(thread_id)


async def test_decision_rejects_second_submit() -> None:
    thread_id = str(uuid.uuid4())
    await _seed_pending(thread_id)
    try:
        with (
            patch.object(rule_documents, "get_checkpointer", lambda: None),
            patch.object(rule_documents, "build_graph", lambda checkpointer=None: _graph(AsyncMock())),
        ):
            await decide_rule_draft(thread_id, _request(), reviewer="tester")
            with pytest.raises(HTTPException) as error:
                await decide_rule_draft(thread_id, _request(), reviewer="tester")
        assert error.value.status_code == 409
    finally:
        await _cleanup(thread_id)


async def test_decision_rejects_count_mismatch() -> None:
    thread_id = str(uuid.uuid4())
    await _seed_pending(thread_id)  # items 1건
    try:
        request = RuleDraftDecisionRequest(
            decisions=[DecisionItem(action="approve"), DecisionItem(action="reject")]
        )
        with pytest.raises(HTTPException) as error:
            await decide_rule_draft(thread_id, request, reviewer="tester")
        assert error.value.status_code == 422
        # 개수가 틀렸으면 선점하지 않고 그대로 둬야 한다.
        assert await _status(thread_id) == "pending"
    finally:
        await _cleanup(thread_id)
