"""[7] 관리자 검수 노드. interrupt()로 그래프를 멈추고 배치 전체를 검수 큐에 노출한다.

**배치 단위 검수(2026-09-27 결정)** — draft 하나하나 interrupt를 거는 대신 문서 실행
전체를 한 번에 interrupt한다.
- 관리자가 실제로 보는 건 "이 문서에서 뽑힌 룰 수십 개를 훑어보고 몇 개만 고친다"는
  목록형 워크플로다. draft마다 승인 API를 따로 호출하게 만들면 번거롭다.
- LangGraph는 resume될 때마다 interrupt() **이전** 코드를 처음부터 재실행한다. draft마다
  interrupt를 거는 설계였다면 이 부가효과(검수 큐 upsert)가 N번 재실행돼 멱등성을 매번
  신경 써야 한다. 단일 interrupt면 이 문제가 사실상 사라진다(upsert 한 번뿐).

auto_validate 통과분(state["drafts"])뿐 아니라, 재시도(retry_extract) 소진 후에도 계속
실패한 draft(state["validation"]["failed_drafts"])도 함께 검수 큐에 올린다 — "자동 폐기
금지" 원칙(langgraph_파이프라인_설계서.md §5.3)이 실패 draft에도 그대로 적용되므로
관리자가 직접 보고 버릴지 살릴지 정해야 한다.
"""

from datetime import datetime, timezone

from langgraph.config import get_config
from langgraph.types import interrupt
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import RuleReviewQueue
from app.db.session import AsyncSessionLocal
from app.pipeline.state import ExtractedDraft, PipelineState


def _build_review_items(state: PipelineState) -> list[dict]:
    validation = state["validation"]
    failed_entries = [] if validation["passed"] else validation["failed_drafts"]

    items = [{"draft": draft, "status": "auto_passed", "reasons": []} for draft in state["drafts"]]
    items += [
        {"draft": entry["draft"], "status": "validation_failed", "reasons": entry["reasons"]}
        for entry in failed_entries
    ]
    return items


async def human_review(state: PipelineState) -> dict:
    items = _build_review_items(state)

    config = get_config()
    thread_id = config["configurable"]["thread_id"]
    await _upsert_pending(thread_id, state["document_id"], items, state["chunks"])

    # decision 형태: {"decisions": [{"action": "approve"|"reject", "reason": str|None,
    #   "edited_fields": dict|None}, ...], "reviewed_by": str}
    # decisions는 items와 순서 1:1 대응 — 관리자 UI가 같은 순서로 제출해야 한다.
    decision = interrupt({"document_id": state["document_id"], "items": items})

    approved: list[ExtractedDraft] = []
    rejected: list[dict] = []
    for item, item_decision in zip(items, decision["decisions"]):
        draft = item["draft"]
        if item_decision["action"] == "approve":
            edited_fields = item_decision.get("edited_fields")
            if edited_fields:
                draft = {**draft, "fields": {**draft["fields"], **edited_fields}}
            approved.append(draft)
        else:
            rejected.append({"draft": draft, "reason": item_decision.get("reason")})

    await _mark_resolved(thread_id, decision["decisions"], decision.get("reviewed_by"))

    return {"drafts": approved, "rejected_drafts": rejected}


async def _upsert_pending(thread_id: str, document_id: str, items: list[dict], chunks: list[dict]) -> None:
    async with AsyncSessionLocal() as session:
        stmt = pg_insert(RuleReviewQueue).values(
            thread_id=thread_id,
            document_id=document_id,
            items=items,
            chunks=chunks,
            status="pending",
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[RuleReviewQueue.thread_id],
            set_={"items": items, "chunks": chunks, "status": "pending", "document_id": document_id},
        )
        await session.execute(stmt)
        await session.commit()


async def _mark_resolved(thread_id: str, decisions: list[dict], reviewed_by: str | None) -> None:
    async with AsyncSessionLocal() as session:
        row = await session.get(RuleReviewQueue, thread_id)
        if row is None:
            return
        row.status = "resolved"
        row.decisions = decisions
        row.reviewed_by = reviewed_by
        row.reviewed_at = datetime.now(timezone.utc)
        await session.commit()
