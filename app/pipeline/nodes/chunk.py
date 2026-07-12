"""[2] 텍스트 추출·청킹 노드.

참고: docs/langgraph_파이프라인_설계서.md §4 (chunk_document)
raw_text를 조문 단위 헤딩(로마숫자 "Ⅲ.2.가" 표기, "제N조"/"제N장" 표기)으로 분할한다.
헤딩이 하나도 없으면 문서 전체를 단일 청크로 취급.
"""

import re
import uuid

from app.pipeline.state import Chunk, PipelineState

# "Ⅲ.2.가" 식 로마숫자 조문 표기 또는 "제3조"/"제2장" 식 법령 조문 표기를 줄 시작에서 탐지
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
        # TODO(설계서 §13-b): 계층형 section_path(장/절/조 경로) 추적은 미구현 — 현재는 article_number로 대체
        "section_path": article_number,
        "content": content,
        "source": "own",
    }
