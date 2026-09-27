"""Stage A/B/C 순차 그래프: ingest_document → chunk_document → [extract_A] → [extract_B] →
[extract_C] → auto_validate → (retry_extract 루프 | human_review) → reject_log → publish.

human_review는 interrupt()로 멈추므로 checkpointer 없이는 그래프를 재개할 방법이 없다 —
build_graph()에 checkpointer를 안 넘기면(테스트 등) interrupt가 있는 human_review까지는
못 가는 그래프로 컴파일된다(LangGraph가 interrupt 사용 시 checkpointer를 요구).
"""

from langgraph.graph import END, START, StateGraph

from app.pipeline.nodes.chunk import chunk_document
from app.pipeline.nodes.classify import classify_document_source
from app.pipeline.nodes.extract_a import extract_A
from app.pipeline.nodes.extract_b import extract_B
from app.pipeline.nodes.extract_c import extract_C
from app.pipeline.nodes.human_review import human_review
from app.pipeline.nodes.ingest import ingest_document
from app.pipeline.nodes.publish import publish
from app.pipeline.nodes.reject_log import reject_log
from app.pipeline.nodes.retry_extract import MAX_RETRY, retry_extract
from app.pipeline.nodes.validate import auto_validate
from app.pipeline.state import PipelineState


def _route_after_classify(state: PipelineState) -> str:
    """청크가 이미 주어졌으면 PDF 적재·청킹을 건너뛴다.

    법령(법률/시행령/시행규칙)은 law.go.kr 본문 API가 조문 단위로 나뉜 텍스트를 주므로
    (app/domain/law_api.py), PDF를 받아 pypdf로 긁고 chunk.py가 헤딩을 추측하는 경로를
    탈 이유가 없다. 개정 대응 시에는 바뀐 조문만 넣어서 검수 배치를 작게 유지하는 용도도
    겸한다. 지침서·안내서류는 API에 없으므로 기존 PDF 경로를 그대로 탄다.
    """
    if state.get("chunks"):
        return _route_after_chunk(state)
    return "ingest_document"


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


def _route_after_validate(state: PipelineState) -> str:
    """langgraph_파이프라인_설계서.md §5.3. 재시도 소진 시에도 검증실패 draft를 버리지
    않고 human_review로 넘긴다(자동 폐기 금지 원칙)."""
    if state["validation"]["passed"]:
        return "human_review"
    if state["retry_count"] < MAX_RETRY:
        return "retry_extract"
    return "human_review"


def build_graph(checkpointer=None):
    graph = StateGraph(PipelineState)

    graph.add_node("classify_document_source", classify_document_source)
    graph.add_node("ingest_document", ingest_document)
    graph.add_node("chunk_document", chunk_document)
    graph.add_node("extract_A", extract_A)
    graph.add_node("extract_B", extract_B)
    graph.add_node("extract_C", extract_C)
    graph.add_node("auto_validate", auto_validate)
    graph.add_node("retry_extract", retry_extract)
    graph.add_node("human_review", human_review)
    graph.add_node("reject_log", reject_log)
    graph.add_node("publish", publish)

    # load_shared_chunks(법령규제문서를 RAG evidence_chunks와 공유하는 경로)는 아직 없다 —
    # app/rag/(팀원 담당) 스키마와 얽혀 있어 사전 협의 없이 구현하지 않는다(classify.py 상단
    # 주석 참고). 대신 law.go.kr API로 받은 조문을 chunks로 미리 채워 넣으면 PDF 경로를
    # 건너뛴다(_route_after_classify).
    graph.add_edge(START, "classify_document_source")
    graph.add_conditional_edges(
        "classify_document_source",
        _route_after_classify,
        {
            "ingest_document": "ingest_document",
            "extract_A": "extract_A",
            "extract_B": "extract_B",
            "extract_C": "extract_C",
            "auto_validate": "auto_validate",
        },
    )
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
    graph.add_conditional_edges(
        "auto_validate",
        _route_after_validate,
        {"retry_extract": "retry_extract", "human_review": "human_review"},
    )
    graph.add_edge("retry_extract", "auto_validate")
    # 배치 검수라 승인·반려가 한 실행에 같이 나올 수 있어(publish/reject_log 양자택일이 아니라)
    # 순차로 둔다 — 두 노드 다 자기 몫이 없으면(승인 0건/반려 0건) 조용히 통과한다.
    graph.add_edge("human_review", "reject_log")
    graph.add_edge("reject_log", "publish")
    graph.add_edge("publish", END)

    return graph.compile(checkpointer=checkpointer)
