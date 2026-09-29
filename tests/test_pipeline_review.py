"""관리자 검수(human_review) e2e 회귀 테스트 — 배치 단위 interrupt/resume이 실제로
동작하는지, 승인분은 publish까지 반영되고 반려분은 publish에서 빠지는지 확인한다.

ingest_document/chunk_document/extract_A는 PDF·LLM 호출이라 목으로 대체하고, auto_validate
→ human_review → reject_log → publish는 실제 로직 그대로(DB는 로컬 docker) 태운다.
InMemorySaver를 써서 Postgres 체크포인터 없이도 interrupt/resume 왕복을 검증한다.
"""

import uuid
from unittest.mock import patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy import delete, select

import app.pipeline.graph as graph_module
from app.db.models import GateKeyword, RuleReviewQueue
from app.db.session import AsyncSessionLocal
from app.pipeline.graph import build_graph

pytestmark = pytest.mark.db

CHUNK_CONTENT = "테스트생체지표리뷰이슈에 대한 조문입니다."


def _fake_chunk() -> dict:
    return {
        "chunk_id": "chunk-review-e2e",
        "document_id": "test-review-doc",
        "article_number": "제1조",
        "section_path": "제1조",
        "content": CHUNK_CONTENT,
        "source": "own",
    }


def _fake_draft(keyword: str) -> dict:
    legal_basis = {
        "document_id": "test-review-doc",
        "article": "제1조",
        "quote": CHUNK_CONTENT,
    }
    return {
        "stage": "A",
        "fields": {
            "type": "DISEASE",
            "keyword": keyword,
            "keyword_category": "DATA_TYPE",
            "data_type_focus": "NONE",
            "verdict": "FAIL_CANDIDATE",
            "weight": 2,
            "legal_basis": legal_basis,
        },
        "legal_basis": legal_basis,
        "source_chunk_id": "chunk-review-e2e",
    }


def _initial_state(document_id: str) -> dict:
    return {
        "source_path": "unused-in-test",
        "document_id": document_id,
        "document_category": "판단가이드",
        "target_stages": ["A"],
        "chunks": [],
        "current_chunk_id": None,
        "current_stage": None,
        "drafts": [],
        "derived_values": {},
        "validation": None,
        "retry_count": 0,
        "rule_version_id": None,
        "rejected_drafts": [],
    }


async def _cleanup(thread_id: str, keywords: list[str]) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(RuleReviewQueue).where(RuleReviewQueue.thread_id == thread_id))
        if keywords:
            await session.execute(delete(GateKeyword).where(GateKeyword.keyword.in_(keywords)))
        await session.commit()


async def test_human_review_batch_approve_and_reject_e2e() -> None:
    keyword_approved = f"승인용테스트키워드_{uuid.uuid4().hex[:8]}"
    keyword_rejected = f"반려용테스트키워드_{uuid.uuid4().hex[:8]}"
    thread_id = str(uuid.uuid4())
    document_id = f"test-review-doc-{uuid.uuid4().hex[:8]}"

    chunk = _fake_chunk()
    draft_approved = _fake_draft(keyword_approved)
    draft_rejected = _fake_draft(keyword_rejected)

    checkpointer = InMemorySaver()
    with (
        patch.object(graph_module, "ingest_document", lambda state: {"document_id": document_id, "document_category": "판단가이드", "raw_text": CHUNK_CONTENT}),
        patch.object(graph_module, "chunk_document", lambda state: {"chunks": [chunk]}),
        patch.object(graph_module, "extract_A", lambda state: {"drafts": [draft_approved, draft_rejected]}),
    ):
        graph = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": thread_id}}

        result = await graph.ainvoke(_initial_state(document_id), config=config)
        assert "__interrupt__" in result, "human_review에서 멈춰야 한다"

        async with AsyncSessionLocal() as session:
            queue_row = await session.get(RuleReviewQueue, thread_id)
        assert queue_row is not None
        assert queue_row.status == "pending"
        assert len(queue_row.items) == 2

        # items 순서는 human_review가 만든 순서(state["drafts"] 순서)와 같다 — extract_A가
        # [approved, rejected] 순으로 넣었으므로 그대로 대응한다.
        decisions = [
            {"action": "approve", "reason": None, "edited_fields": None},
            {"action": "reject", "reason": "테스트 반려", "edited_fields": None},
        ]
        await graph.ainvoke(
            Command(resume={"decisions": decisions, "reviewed_by": "tester"}), config=config
        )

    try:
        async with AsyncSessionLocal() as session:
            queue_row = await session.get(RuleReviewQueue, thread_id)
            # status는 노드가 아니라 API가 publish 성공까지 보고 확정한다(rule_documents.py) —
            # 그래프만 직접 태우는 이 테스트에서는 pending 그대로다.
            assert queue_row.status == "pending"
            assert queue_row.reviewed_by == "tester"
            assert len(queue_row.decisions) == 2

            rows = (
                await session.execute(
                    select(GateKeyword).where(
                        GateKeyword.keyword.in_([keyword_approved, keyword_rejected])
                    )
                )
            ).scalars().all()
            keywords_in_db = {row.keyword for row in rows}
        assert keyword_approved in keywords_in_db, "승인된 draft는 publish로 실제 테이블에 반영돼야 한다"
        assert keyword_rejected not in keywords_in_db, "반려된 draft는 publish에 포함되면 안 된다"
    finally:
        await _cleanup(thread_id, [keyword_approved, keyword_rejected])
