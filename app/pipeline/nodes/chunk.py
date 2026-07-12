"""[2] 텍스트 추출·청킹 노드. 조문 헤딩 단위로 raw_text를 분할하고, 헤딩이 없으면 전체를 단일 청크로 취급."""

import re
import uuid

from app.pipeline.state import Chunk, PipelineState

_HEADING_PATTERN = re.compile(
    r"^(?P<heading>"
    r"[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+(?:\.\d+)?(?:\.[가-하])?"
    r"|제\d+조(?:의\d+)?(?:\([^)]*\))?"
    r"|제\d+장"
    r")",
    re.MULTILINE,
)


def chunk_document(state: PipelineState) -> dict:
    raw_text = state["raw_text"]
    matches = list(_HEADING_PATTERN.finditer(raw_text))

    chunks: list[Chunk] = []
    if not matches:
        chunks.append(_build_chunk(state, article_number="", content=raw_text))
    else:
        for i, match in enumerate(matches):
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(raw_text)
            article_number = match.group("heading").strip()
            content = raw_text[start:end].strip()
            chunks.append(_build_chunk(state, article_number=article_number, content=content))

    return {"chunks": chunks}


def _build_chunk(state: PipelineState, article_number: str, content: str) -> Chunk:
    return {
        "chunk_id": str(uuid.uuid4()),
        "document_id": state["document_id"],
        "article_number": article_number,
        "section_path": article_number,  # TODO: 계층형 경로 미구현
        "content": content,
        "source": "own",
    }
