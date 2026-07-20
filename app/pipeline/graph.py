"""Stage A/B/C 순차 그래프: ingest_document → chunk_document → [extract_A] → [extract_B] →
[extract_C] → auto_validate → publish.
"""

from langgraph.graph import END, START, StateGraph

from app.pipeline.nodes.chunk import chunk_document
from app.pipeline.nodes.extract_a import extract_A
from app.pipeline.nodes.extract_b import extract_B
from app.pipeline.nodes.extract_c import extract_C
from app.pipeline.nodes.ingest import ingest_document
from app.pipeline.nodes.publish import publish
from app.pipeline.nodes.validate import auto_validate
from app.pipeline.state import PipelineState


def _route_after_chunk(state: PipelineState) -> str:
    if "A" in state["target_stages"]:
        return "extract_A"
    if "B" in state["target_stages"]:
        return "extract_B"
    if "C" in state["target_stages"]:
        return "extract_C"
    return "auto_validate"


def _route_after_extract_a(state: PipelineState) -> str:
    if "B" in state["target_stages"]:
        return "extract_B"
    if "C" in state["target_stages"]:
        return "extract_C"
    return "auto_validate"


def _route_after_extract_b(state: PipelineState) -> str:
    if "C" in state["target_stages"]:
        return "extract_C"
    return "auto_validate"


def build_graph():
    graph = StateGraph(PipelineState)

    graph.add_node("ingest_document", ingest_document)
    graph.add_node("chunk_document", chunk_document)
    graph.add_node("extract_A", extract_A)
    graph.add_node("extract_B", extract_B)
    graph.add_node("extract_C", extract_C)
    graph.add_node("auto_validate", auto_validate)
    graph.add_node("publish", publish)

    graph.add_edge(START, "ingest_document")
    graph.add_edge("ingest_document", "chunk_document")
    graph.add_conditional_edges(
        "chunk_document",
        _route_after_chunk,
        {"extract_A": "extract_A", "extract_B": "extract_B", "extract_C": "extract_C", "auto_validate": "auto_validate"},
    )
    graph.add_conditional_edges(
        "extract_A",
        _route_after_extract_a,
        {"extract_B": "extract_B", "extract_C": "extract_C", "auto_validate": "auto_validate"},
    )
    graph.add_conditional_edges(
        "extract_B",
        _route_after_extract_b,
        {"extract_C": "extract_C", "auto_validate": "auto_validate"},
    )
    graph.add_edge("extract_C", "auto_validate")
    graph.add_edge("auto_validate", "publish")
    graph.add_edge("publish", END)

    return graph.compile()
