from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.config import settings
from app.db.models.evidence_chunk import EvidenceChunk
from app.db.models.evidence_document import EvidenceDocument
from app.db.session import AsyncSessionLocal
from app.rag.retriever import EvidenceRetriever
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])

_evidence_retriever: EvidenceRetriever | None = None


def _get_evidence_retriever() -> EvidenceRetriever:
    """요청마다 새 OpenAI 클라이언트를 만들지 않도록 최초 1회만 생성해 재사용한다.

    OPENAI_API_KEY 미설정 시 EvidenceRetriever() 생성 자체가 RuntimeError를 던지므로,
    앱 기동(모듈 임포트) 시점이 아니라 키 존재가 확인된 첫 요청 시점에 지연 생성한다.
    """
    global _evidence_retriever
    if _evidence_retriever is None:
        _evidence_retriever = EvidenceRetriever()
    return _evidence_retriever


DocType = Literal["LAW", "GUIDE", "CASE", "REPORT"]
DocumentStatus = Literal["active", "future", "draft", "pending_source"]


class RagDocumentCore(BaseModel):
    document_id: str
    title: str
    doc_type: str
    source_subtype: str | None
    effective_date: date | None
    status: str


class RagDocumentListItem(RagDocumentCore):
    tag_regulatory: bool
    tag_privacy: bool
    tag_advertising: bool


class RagDocumentDetail(RagDocumentCore):
    issuing_org: str | None
    source_url: str | None


class RagChunkLookupRequest(BaseModel):
    document_id: str
    section_ids: list[str] = Field(max_length=50)


class RagChunkCore(BaseModel):
    chunk_id: str
    document_id: str
    section_id: str | None
    section_title: str | None
    chunk_text: str
    source_url: str | None
    page_start: int | None
    page_end: int | None


class RagChunkLookupItem(RagChunkCore):
    pass


class RagSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    tag_regulatory: bool | None = None
    tag_privacy: bool | None = None
    tag_advertising: bool | None = None
    document_ids: list[str] | None = None


class RagSearchResult(RagChunkCore):
    title: str
    doc_type: str
    similarity: float


class RagDocumentsResponse(ApiResponse):
    result: list[RagDocumentListItem]
    total: int


class RagDocumentResponse(ApiResponse):
    result: RagDocumentDetail


class RagErrorResponse(ApiResponse):
    result: None = None


class RagChunksLookupResponse(ApiResponse):
    result: list[RagChunkLookupItem]


@router.get("/documents", response_model=RagDocumentsResponse)
async def list_rag_documents(
    doc_type: DocType | None = Query(default=None),
    tag_regulatory: bool | None = Query(default=None),
    tag_privacy: bool | None = Query(default=None),
    tag_advertising: bool | None = Query(default=None),
    status: DocumentStatus | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> RagDocumentsResponse:
    filters = []
    if doc_type:
        filters.append(EvidenceDocument.doc_type == doc_type)
    if tag_regulatory is not None:
        filters.append(EvidenceDocument.tag_regulatory == tag_regulatory)
    if tag_privacy is not None:
        filters.append(EvidenceDocument.tag_privacy == tag_privacy)
    if tag_advertising is not None:
        filters.append(EvidenceDocument.tag_advertising == tag_advertising)
    filters.append(EvidenceDocument.status == (status or "active"))

    stmt = (
        select(EvidenceDocument)
        .where(*filters)
        .order_by(EvidenceDocument.doc_type, EvidenceDocument.title, EvidenceDocument.document_id)
        .limit(limit)
        .offset(offset)
    )
    count_stmt = select(func.count()).select_from(EvidenceDocument).where(*filters)

    async with AsyncSessionLocal() as session:
        documents = (await session.execute(stmt)).scalars().all()
        total = (await session.execute(count_stmt)).scalar_one()

    return RagDocumentsResponse(
        isSuccess=True,
        code="RAG_DOCUMENTS_FOUND",
        message="RAG 문서 목록을 조회했습니다.",
        total=total,
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


@router.get(
    "/documents/{document_id}",
    response_model=RagDocumentResponse,
    responses={404: {"model": RagErrorResponse}},
)
async def get_rag_document(document_id: str) -> RagDocumentResponse | JSONResponse:
    async with AsyncSessionLocal() as session:
        document = await session.get(EvidenceDocument, document_id)

    if document is None:
        return JSONResponse(
            status_code=404,
            content=RagErrorResponse(
                isSuccess=False,
                code="RAG_DOCUMENT_NOT_FOUND",
                message="RAG 문서를 찾을 수 없습니다.",
            ).model_dump(),
        )

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


def order_chunks_by_requested_sections(
    chunks: Sequence[EvidenceChunk], section_ids: list[str]
) -> list[EvidenceChunk]:
    """chunk_order가 아니라 caller가 요청한 section_ids 순서를 따르도록 재정렬한다.

    중복 section_id가 오면 첫 등장 위치를 기준으로 삼는다 — setdefault라서 뒤에 나온
    같은 id는 앞의 순번을 덮어쓰지 않는다.
    """
    section_order: dict[str, int] = {}
    for index, section_id in enumerate(section_ids):
        section_order.setdefault(section_id, index)
    return sorted(chunks, key=lambda chunk: section_order.get(chunk.section_id or "", len(section_order)))


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
        .join(EvidenceDocument, EvidenceDocument.document_id == EvidenceChunk.document_id)
        .where(EvidenceChunk.document_id == request.document_id)
        .where(EvidenceChunk.section_id.in_(request.section_ids))
        .where(EvidenceChunk.status == "active")
        .where(EvidenceDocument.status == "active")
        .order_by(EvidenceChunk.chunk_order)
    )
    async with AsyncSessionLocal() as session:
        chunks = (await session.execute(stmt)).scalars().all()

    chunks = order_chunks_by_requested_sections(chunks, request.section_ids)

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


@router.post(
    "/search",
    response_model=list[RagSearchResult],
    responses={503: {"model": RagErrorResponse}},
)
async def search_rag_evidence(request: RagSearchRequest) -> list[RagSearchResult] | JSONResponse:
    if not settings.openai_api_key:
        return JSONResponse(
            status_code=503,
            content=RagErrorResponse(
                isSuccess=False,
                code="RAG_SEARCH_UNAVAILABLE",
                message="OPENAI_API_KEY가 설정되지 않았습니다.",
            ).model_dump(),
        )

    retriever = _get_evidence_retriever()
    chunks = await retriever.search(
        request.query,
        top_k=request.top_k,
        tag_regulatory=request.tag_regulatory,
        tag_privacy=request.tag_privacy,
        tag_advertising=request.tag_advertising,
        document_ids=request.document_ids,
    )
    return [
        RagSearchResult(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            title=chunk.title,
            doc_type=chunk.doc_type,
            section_id=chunk.section_id,
            section_title=chunk.section_title,
            chunk_text=chunk.chunk_text,
            source_url=chunk.source_url,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            similarity=chunk.similarity,
        )
        for chunk in chunks
    ]
