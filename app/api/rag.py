from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.db.models.evidence_chunk import EvidenceChunk
from app.db.models.evidence_document import EvidenceDocument
from app.db.session import AsyncSessionLocal

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])

DocType = Literal["LAW", "GUIDE", "CASE", "REPORT"]
DocumentStatus = Literal["active", "future", "draft", "pending_source"]


class ApiResponse(BaseModel):
    isSuccess: bool
    code: str
    message: str
    result: object


class RagDocumentListItem(BaseModel):
    document_id: str
    title: str
    doc_type: str
    source_subtype: str | None
    status: str
    effective_date: date | None
    tag_regulatory: bool
    tag_privacy: bool
    tag_advertising: bool


class RagDocumentDetail(BaseModel):
    document_id: str
    title: str
    doc_type: str
    source_subtype: str | None
    issuing_org: str | None
    effective_date: date | None
    status: str
    source_url: str | None


class RagChunkLookupRequest(BaseModel):
    document_id: str
    section_ids: list[str]


class RagChunkLookupItem(BaseModel):
    chunk_id: str
    document_id: str
    section_id: str | None
    section_title: str | None
    chunk_text: str
    source_url: str | None
    page_start: int | None
    page_end: int | None


class RagDocumentsResponse(BaseModel):
    isSuccess: bool
    code: str
    message: str
    result: list[RagDocumentListItem]


class RagDocumentResponse(BaseModel):
    isSuccess: bool
    code: str
    message: str
    result: RagDocumentDetail


class RagChunksLookupResponse(BaseModel):
    isSuccess: bool
    code: str
    message: str
    result: list[RagChunkLookupItem]


@router.get("/documents", response_model=RagDocumentsResponse)
async def list_rag_documents(
    doc_type: DocType | None = Query(default=None),
    tag_regulatory: bool | None = Query(default=None),
    tag_privacy: bool | None = Query(default=None),
    tag_advertising: bool | None = Query(default=None),
    status: DocumentStatus | None = Query(default=None),
) -> RagDocumentsResponse:
    stmt = select(EvidenceDocument)
    if doc_type:
        stmt = stmt.where(EvidenceDocument.doc_type == doc_type)
    if tag_regulatory is not None:
        stmt = stmt.where(EvidenceDocument.tag_regulatory == tag_regulatory)
    if tag_privacy is not None:
        stmt = stmt.where(EvidenceDocument.tag_privacy == tag_privacy)
    if tag_advertising is not None:
        stmt = stmt.where(EvidenceDocument.tag_advertising == tag_advertising)
    if status:
        stmt = stmt.where(EvidenceDocument.status == status)
    stmt = stmt.order_by(EvidenceDocument.doc_type, EvidenceDocument.title, EvidenceDocument.document_id)

    async with AsyncSessionLocal() as session:
        documents = (await session.execute(stmt)).scalars().all()

    return RagDocumentsResponse(
        isSuccess=True,
        code="RAG_DOCUMENTS_FOUND",
        message="RAG 문서 목록을 조회했습니다.",
        result=[
            RagDocumentListItem(
                document_id=document.document_id,
                title=document.title,
                doc_type=document.doc_type,
                source_subtype=document.source_subtype,
                status=document.status,
                effective_date=document.effective_date,
                tag_regulatory=document.tag_regulatory,
                tag_privacy=document.tag_privacy,
                tag_advertising=document.tag_advertising,
            )
            for document in documents
        ],
    )


@router.get("/documents/{document_id}", response_model=RagDocumentResponse)
async def get_rag_document(document_id: str) -> RagDocumentResponse:
    async with AsyncSessionLocal() as session:
        document = await session.get(EvidenceDocument, document_id)

    if document is None:
        raise HTTPException(status_code=404, detail="RAG document not found.")

    return RagDocumentResponse(
        isSuccess=True,
        code="RAG_DOCUMENT_FOUND",
        message="RAG 문서를 조회했습니다.",
        result=RagDocumentDetail(
            document_id=document.document_id,
            title=document.title,
            doc_type=document.doc_type,
            source_subtype=document.source_subtype,
            issuing_org=document.issuing_org,
            effective_date=document.effective_date,
            status=document.status,
            source_url=document.source_url,
        ),
    )


@router.post("/chunks/lookup", response_model=RagChunksLookupResponse)
async def lookup_rag_chunks(request: RagChunkLookupRequest) -> RagChunksLookupResponse:
    if not request.section_ids:
        return RagChunksLookupResponse(
            isSuccess=True,
            code="RAG_CHUNKS_FOUND",
            message="근거 chunk를 조회했습니다.",
            result=[],
        )

    stmt = (
        select(EvidenceChunk)
        .where(EvidenceChunk.document_id == request.document_id)
        .where(EvidenceChunk.section_id.in_(request.section_ids))
        .where(EvidenceChunk.status == "active")
        .order_by(EvidenceChunk.chunk_order)
    )
    async with AsyncSessionLocal() as session:
        chunks = (await session.execute(stmt)).scalars().all()

    section_order = {section_id: index for index, section_id in enumerate(request.section_ids)}
    chunks = sorted(chunks, key=lambda chunk: section_order.get(chunk.section_id or "", len(section_order)))

    return RagChunksLookupResponse(
        isSuccess=True,
        code="RAG_CHUNKS_FOUND",
        message="근거 chunk를 조회했습니다.",
        result=[
            RagChunkLookupItem(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                section_id=chunk.section_id,
                section_title=chunk.section_title,
                chunk_text=chunk.chunk_text,
                source_url=chunk.source_url,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
            )
            for chunk in chunks
        ],
    )
