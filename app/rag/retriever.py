from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.rag.embeddings import EmbeddingClient, to_pgvector_literal


@dataclass(frozen=True)
class RetrievedEvidenceChunk:
    chunk_id: str
    document_id: str
    title: str
    doc_type: str
    section_id: str | None
    section_title: str | None
    chunk_text: str
    source_url: str | None
    page_start: int | None
    page_end: int | None
    similarity: float


class EvidenceRetriever:
    def __init__(self, embedding_client: EmbeddingClient | None = None) -> None:
        self.embedding_client = embedding_client or EmbeddingClient()

    async def search(
        self,
        session: AsyncSession,
        query: str,
        *,
        top_k: int | None = None,
        tag_regulatory: bool | None = None,
        tag_privacy: bool | None = None,
        tag_advertising: bool | None = None,
        document_ids: list[str] | None = None,
    ) -> list[RetrievedEvidenceChunk]:
        query_embedding = await self.embedding_client.embed_query(query)
        embedding_literal = to_pgvector_literal(query_embedding)

        filters = [
            "ec.status = 'active'",
            "ed.status = 'active'",
            "ed.usage_scope IN ('RAG', 'BOTH')",
            "ece.embedding_model = :embedding_model",
        ]
        params: dict[str, object] = {
            "embedding": embedding_literal,
            "embedding_model": self.embedding_client.model,
            "limit": top_k or settings.rag_retrieval_top_k,
        }

        if tag_regulatory is not None:
            filters.append("ec.tag_regulatory = :tag_regulatory")
            params["tag_regulatory"] = tag_regulatory
        if tag_privacy is not None:
            filters.append("ec.tag_privacy = :tag_privacy")
            params["tag_privacy"] = tag_privacy
        if tag_advertising is not None:
            filters.append("ec.tag_advertising = :tag_advertising")
            params["tag_advertising"] = tag_advertising
        if document_ids:
            filters.append("ec.document_id IN :document_ids")
            params["document_ids"] = document_ids

        where_clause = " AND ".join(filters)
        stmt = text(
            f"""
            SELECT
                ec.chunk_id,
                ec.document_id,
                ed.title,
                ed.doc_type,
                ec.section_id,
                ec.section_title,
                ec.chunk_text,
                COALESCE(ec.source_url, ed.source_url) AS source_url,
                ec.page_start,
                ec.page_end,
                1 - (ece.embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM evidence_chunk_embeddings ece
            JOIN evidence_chunks ec ON ec.chunk_id = ece.chunk_id
            JOIN evidence_documents ed ON ed.document_id = ec.document_id
            WHERE {where_clause}
            ORDER BY ece.embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
            """
        )
        if document_ids:
            stmt = stmt.bindparams(bindparam("document_ids", expanding=True))

        rows = (await session.execute(stmt, params)).mappings().all()
        return [RetrievedEvidenceChunk(**row) for row in rows]
