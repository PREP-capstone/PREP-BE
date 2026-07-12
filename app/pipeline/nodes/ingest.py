"""[1] PDF 업로드 노드. 문서 분류 분기가 아직 없어 모든 문서를 "own" 경로로 취급한다."""

import uuid

from pypdf import PdfReader

from app.pipeline.state import PipelineState


def ingest_document(state: PipelineState) -> dict:
    reader = PdfReader(state.get("source_path"))
    raw_text = "\n".join(page.extract_text() or "" for page in reader.pages)

    # TODO: evidence_documents 생성은 팀원 공유 모델이라 보류
    return {
        "document_id": str(uuid.uuid4()),
        "document_category": state.get("document_category") or "판단가이드",
        "raw_text": raw_text,
    }
