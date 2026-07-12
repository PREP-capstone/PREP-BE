"""Stage A 순차 그래프: ingest_document → chunk_document → extract_A → auto_validate → publish.
classify_document_source/route_stage(Send)/retry_extract/human_review/reject_log는 아직 없음.
async 노드가 섞여있어 `ainvoke()`로 실행해야 한다 (`.invoke()` 사용 금지).
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
