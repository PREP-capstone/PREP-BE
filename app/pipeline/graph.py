"""LangGraph 그래프 정의.

참고: docs/langgraph_파이프라인_설계서.md §2, §10
현재는 Stage A만 순차 실행으로 구현한다:
    ingest_document → chunk_document → extract_A → auto_validate → publish

아직 붙지 않은 것들 (뒤에 확장 예정):
- classify_document_source / load_shared_chunks (§2, §5.0) — 법령·규제 문서 vs 판단가이드 분기
- route_stage (§5.1, Send) — Stage A/B/C/D 병렬 팬아웃
- route_after_extract (§5.2) — Stage C의 derive_scores 분기
- route_after_validate (§5.3) — retry_extract / human_review 조건부 분기
- retry_extract, human_review(interrupt), reject_log

extract_A/auto_validate/publish는 LLM 호출·DB I/O 때문에 async 노드다. 이 그래프는
반드시 `await compiled_graph.ainvoke(...)`로 실행해야 한다 (`.invoke()` 사용 금지).
"""

from langgraph.graph import END, START, StateGraph

from app.pipeline.nodes.chunk import chunk_document
from app.pipeline.nodes.extract_a import extract_A
from app.pipeline.nodes.ingest import ingest_document
from app.pipeline.nodes.publish import publish
from app.pipeline.nodes.validate import auto_validate
from app.pipeline.state import PipelineState


def build_graph():
    graph = StateGraph(PipelineState)

    graph.add_node("ingest_document", ingest_document)
    graph.add_node("chunk_document", chunk_document)
    graph.add_node("extract_A", extract_A)
    graph.add_node("auto_validate", auto_validate)
    graph.add_node("publish", publish)

    graph.add_edge(START, "ingest_document")
    graph.add_edge("ingest_document", "chunk_document")
    graph.add_edge("chunk_document", "extract_A")
    graph.add_edge("extract_A", "auto_validate")
    graph.add_edge("auto_validate", "publish")
    graph.add_edge("publish", END)

    return graph.compile()
