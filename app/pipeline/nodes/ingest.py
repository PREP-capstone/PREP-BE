"""[1] PDF 업로드 노드. 문서 분류 분기가 아직 없어 모든 문서를 "own" 경로로 취급한다."""

from pathlib import Path

from pypdf import PdfReader

from app.pipeline.state import PipelineState


def ingest_document(state: PipelineState) -> dict:
    source_path = state.get("source_path")
    reader = PdfReader(source_path)
    raw_text = "\n".join(page.extract_text() or "" for page in reader.pages)

    # document_id는 파일명(확장자 제외)을 그대로 쓴다. RAG evidence_documents.document_id와
    # 동일한 규칙이라야 legal_basis_doc ↔ evidence_documents 조인이 성립한다.
    # (예전에는 uuid4를 발급해서 legal_basis_doc에 임의의 UUID가 들어가고 있었다.)
    # 호출자가 document_id를 명시했으면 그 값을 우선한다.
    document_id = state.get("document_id") or Path(source_path).stem

    # TODO: evidence_documents 생성은 팀원 공유 모델이라 보류
    return {
        "document_id": document_id,
        "document_category": state.get("document_category") or "판단가이드",
        "raw_text": raw_text,
    }
