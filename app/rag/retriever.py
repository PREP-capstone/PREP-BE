from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.rag.embeddings import EmbeddingClient
from app.rag.vector_store import get_evidence_collection


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
        where = _build_where(
            tag_regulatory=tag_regulatory,
            tag_privacy=tag_privacy,
            tag_advertising=tag_advertising,
            document_ids=document_ids,
            embedding_model=self.embedding_client.model,
        )

        collection = get_evidence_collection()
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k or settings.rag_retrieval_top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        chunks: list[RetrievedEvidenceChunk] = []
        for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances, strict=True):
            chunks.append(
                RetrievedEvidenceChunk(
                    chunk_id=chunk_id,
                    document_id=metadata["document_id"],
                    title=metadata["title"],
                    doc_type=metadata["doc_type"],
                    section_id=metadata.get("section_id") or None,
                    section_title=metadata.get("section_title") or None,
                    chunk_text=document,
                    source_url=metadata.get("source_url") or None,
                    page_start=metadata.get("page_start"),
                    page_end=metadata.get("page_end"),
                    similarity=1 - float(distance),
                )
            )
        return chunks


def _build_where(
    *,
    tag_regulatory: bool | None,
    tag_privacy: bool | None,
    tag_advertising: bool | None,
    document_ids: list[str] | None,
    embedding_model: str,
) -> dict:
    conditions: list[dict] = [
        {"status": "active"},
        {"document_status": "active"},
        {"usage_scope": {"$in": ["RAG", "BOTH"]}},
        {"embedding_model": embedding_model},
    ]
    if tag_regulatory is not None:
        conditions.append({"tag_regulatory": tag_regulatory})
    if tag_privacy is not None:
        conditions.append({"tag_privacy": tag_privacy})
    if tag_advertising is not None:
        conditions.append({"tag_advertising": tag_advertising})
    if document_ids:
        conditions.append({"document_id": {"$in": document_ids}})

    return conditions[0] if len(conditions) == 1 else {"$and": conditions}
