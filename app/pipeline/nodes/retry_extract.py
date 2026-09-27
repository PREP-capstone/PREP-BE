"""[신규] auto_validate 실패 시 실패 사유를 프롬프트에 첨부해 같은 청크만 재추출한다
(langgraph_파이프라인_설계서.md §5.3/§8, 최대 MAX_RETRY회).

extract_A/B/C가 이미 청크 단위 헬퍼(extract_chunk_A 등)로 쪼개져 있어, 여기서는 실패한
draft가 어느 청크(source_chunk_id)·어느 Stage에서 나왔는지만 역추적해 그 헬퍼를 그대로
재호출한다 — 추출 로직 자체를 중복 구현하지 않는다.
"""

import json

from openai import AsyncOpenAI

from app.core.config import settings
from app.pipeline.nodes.extract_a import extract_chunk_A
from app.pipeline.nodes.extract_b import extract_chunk_B
from app.pipeline.nodes.extract_c import _load_active_keywords, extract_chunk_C
from app.pipeline.state import ExtractedDraft, PipelineState

MAX_RETRY = 3


def _build_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key)


def _build_extra_context(failed: list[dict]) -> str:
    """실패한 draft들(같은 청크 출신)의 이전 출력·사유를 프롬프트에 첨부할 문자열로 만든다."""
    lines = ["[이전 추출 시도 실패 — 아래 항목이 자동 검증에서 거부됐습니다. 같은 사유로 다시 실패하지 않도록 값을 고쳐서 다시 추출하세요.]"]
    for entry in failed:
        reasons = ", ".join(entry["reasons"])
        lines.append(f"- 이전 출력: {json.dumps(entry['draft']['fields'], ensure_ascii=False)}")
        lines.append(f"  실패 사유: {reasons}")
    return "\n".join(lines)


def _group_by_chunk(failed_drafts: list[dict]) -> dict[tuple[str, str], list[dict]]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for entry in failed_drafts:
        key = (entry["draft"]["stage"], entry["draft"]["source_chunk_id"])
        groups.setdefault(key, []).append(entry)
    return groups


async def retry_extract(state: PipelineState) -> dict:
    failed_drafts = state["validation"]["failed_drafts"]
    chunks_by_id = {chunk["chunk_id"]: chunk for chunk in state["chunks"]}
    client = _build_client()

    drafts: list[ExtractedDraft] = list(state["drafts"])
    active_keywords = None  # Stage C가 실제로 있을 때만 로드(불필요한 DB 조회 방지)

    for (stage, chunk_id), group in _group_by_chunk(failed_drafts).items():
        chunk = chunks_by_id.get(chunk_id)
        extra_context = _build_extra_context(group)

        if chunk is not None and stage == "A":
            drafts.extend(await extract_chunk_A(client, chunk, state["document_id"], extra_context))
        elif chunk is not None and stage == "B":
            drafts.extend(await extract_chunk_B(client, chunk, state["document_id"], extra_context))
        elif chunk is not None and stage == "C":
            if active_keywords is None:
                active_keywords = await _load_active_keywords()
            drafts.extend(
                await extract_chunk_C(client, chunk, state["document_id"], active_keywords, extra_context)
            )
        else:
            # Stage D(미구현)이거나 원본 청크를 못 찾은 경우 — 재추출할 방법이 없다고 원본
            # draft를 버리면 "자동 폐기 금지"(§5.3) 원칙이 깨져서 human_review 큐에서 영영
            # 사라진다. 그대로 다시 실어서 다음 auto_validate에서도 보이게 하고, 결국
            # retry_count 소진 시 human_review로 넘어가게 한다.
            drafts.extend(entry["draft"] for entry in group)

    return {"drafts": drafts, "retry_count": state["retry_count"] + 1}
