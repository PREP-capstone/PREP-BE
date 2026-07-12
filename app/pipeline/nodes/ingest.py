"""[1] PDF 업로드 노드.

참고: docs/langgraph_파이프라인_설계서.md §4 (ingest_document)
현재는 Stage A 순차 실행 경로만 구현 — classify_document_source/load_shared_chunks
분기(설계서 §2, §5.0)는 아직 붙지 않았으므로 모든 문서를 "own" 경로로 취급한다.
"""

import uuid

from pypdf import PdfReader

from app.pipeline.state import PipelineState


def ingest_document(state: PipelineState) -> dict:
    reader = PdfReader(state.get("source_path"))
    raw_text = "\n".join(page.extract_text() or "" for page in reader.pages)

    # TODO: evidence_documents 레코드 생성 (db_구축_설계서.md §4.1 [1]) — app/db/models/evidence.py는
    #   팀원과 공유하는 모델이라 CLAUDE.md에 따라 사전 협의 없이 만들지 않음(설계서 §13-e·f 참조).
    # TODO(설계서 §5.0): classify_document_source 노드가 붙으면 document_category 분기에 따라
    #   load_shared_chunks(법령규제문서)로 라우팅할지 여기로 들어올지 갈린다. 지금은 이 노드가
    #   호출된다는 것 자체가 "판단가이드/위험표현사전" 경로라고 가정한다.
    return {
        "document_id": str(uuid.uuid4()),
        "document_category": state.get("document_category") or "판단가이드",
        "raw_text": raw_text,
    }
