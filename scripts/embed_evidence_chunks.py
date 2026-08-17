from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.rag.embeddings import EmbeddingClient, content_hash
from app.rag.vector_store import get_evidence_collection


SELECT_ACTIVE_IDS_SQL = """
SELECT ec.chunk_id
FROM evidence_chunks ec
JOIN evidence_documents ed ON ed.document_id = ec.document_id
WHERE ec.status = 'active'
  AND ed.status = 'active'
  AND ed.usage_scope IN ('RAG', 'BOTH')
  {document_filter}
ORDER BY ec.document_id, ec.chunk_order
"""


SELECT_CANDIDATES_SQL = """
SELECT
    ec.chunk_id,
    ec.chunk_text,
    ec.document_id,
    ed.title,
    ed.doc_type,
    ec.section_id,
    ec.section_title,
    COALESCE(ec.source_url, ed.source_url) AS source_url,
    ec.page_start,
    ec.page_end,
    ec.tag_regulatory,
    ec.tag_privacy,
    ec.tag_advertising,
    ec.case_tag_advertising,
    ec.case_tag_privacy,
    ec.case_tag_medical_device,
    ec.case_tag_health_functional_food,
    ec.status,
    ed.status AS document_status,
    ed.usage_scope
FROM evidence_chunks ec
JOIN evidence_documents ed ON ed.document_id = ec.document_id
WHERE ec.status = 'active'
  AND ed.status = 'active'
  AND ed.usage_scope IN ('RAG', 'BOTH')
  {document_filter}
ORDER BY ec.document_id, ec.chunk_order
"""


def batched[T](items: list[T], size: int) -> list[list[T]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


def _metadata(row: dict, row_hash: str, embedding_model: str) -> dict:
    return {
        "document_id": row["document_id"],
        "title": row["title"],
        "doc_type": row["doc_type"],
        "section_id": row["section_id"] or "",
        "section_title": row["section_title"] or "",
        "source_url": row["source_url"] or "",
        "page_start": row["page_start"] if row["page_start"] is not None else -1,
        "page_end": row["page_end"] if row["page_end"] is not None else -1,
        "tag_regulatory": bool(row["tag_regulatory"]),
        "tag_privacy": bool(row["tag_privacy"]),
        "tag_advertising": bool(row["tag_advertising"]),
        "case_tag_advertising": bool(row["case_tag_advertising"]),
        "case_tag_privacy": bool(row["case_tag_privacy"]),
        "case_tag_medical_device": bool(row["case_tag_medical_device"]),
        "case_tag_health_functional_food": bool(row["case_tag_health_functional_food"]),
        "status": row["status"],
        "document_status": row["document_status"],
        "usage_scope": row["usage_scope"],
        "embedding_model": embedding_model,
        "content_hash": row_hash,
    }


def _existing_hashes(chunk_ids: list[str]) -> dict[str, str]:
    collection = get_evidence_collection()
    existing: dict[str, str] = {}
    for batch in batched(chunk_ids, 500):
        result = collection.get(ids=batch, include=["metadatas"])
        for chunk_id, metadata in zip(result.get("ids", []), result.get("metadatas", []), strict=True):
            if metadata and metadata.get("content_hash"):
                existing[chunk_id] = metadata["content_hash"]
    return existing


async def load_active_chunk_ids(document_id: str | None) -> set[str]:
    document_filter = "AND ec.document_id = :document_id" if document_id else ""
    query = SELECT_ACTIVE_IDS_SQL.format(document_filter=document_filter)
    params = {}
    if document_id:
        params["document_id"] = document_id

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(text(query), params)).scalars().all()
    return set(rows)


def delete_stale_embeddings(active_chunk_ids: set[str], document_id: str | None, embedding_model: str) -> int:
    collection = get_evidence_collection()
    where = {"embedding_model": embedding_model}
    if document_id:
        where = {"$and": [where, {"document_id": document_id}]}

    result = collection.get(where=where, include=["metadatas"])
    stale_ids = [chunk_id for chunk_id in result.get("ids", []) if chunk_id not in active_chunk_ids]
    if stale_ids:
        collection.delete(ids=stale_ids)
    return len(stale_ids)


async def load_candidate_chunks(document_id: str | None, embedding_model: str, force: bool) -> list[dict]:
    document_filter = "AND ec.document_id = :document_id" if document_id else ""
    query = SELECT_CANDIDATES_SQL.format(document_filter=document_filter)
    params = {}
    if document_id:
        params["document_id"] = document_id

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(query),
                params,
            )
        ).mappings().all()

    row_dicts = [dict(row) for row in rows]
    existing_hashes = {} if force else _existing_hashes([row["chunk_id"] for row in row_dicts])

    candidates: list[dict] = []
    for row in row_dicts:
        row_hash = content_hash(row["chunk_text"])
        if force or existing_hashes.get(row["chunk_id"]) != row_hash:
            candidates.append({
                "chunk_id": row["chunk_id"],
                "chunk_text": row["chunk_text"],
                "content_hash": row_hash,
                "metadata": _metadata(row, row_hash, embedding_model),
            })
    return candidates


async def upsert_embeddings(rows: list[dict], embeddings: list[list[float]], client: EmbeddingClient) -> None:
    collection = get_evidence_collection()
    collection.upsert(
        ids=[row["chunk_id"] for row in rows],
        documents=[row["chunk_text"] for row in rows],
        metadatas=[row["metadata"] for row in rows],
        embeddings=embeddings,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ChromaDB embeddings for evidence_chunks.")
    parser.add_argument("--document-id", help="Embed one evidence document only.")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--force", action="store_true", help="Regenerate embeddings even if text hash matches.")
    parser.add_argument(
        "--sync-delete-stale",
        action="store_true",
        help="Delete Chroma embeddings that no longer exist as active DB evidence_chunks.",
    )
    parser.add_argument("--dry-run", action="store_true", help="List candidate count without OpenAI calls.")
    args = parser.parse_args()

    active_chunk_ids = await load_active_chunk_ids(args.document_id)
    candidates = await load_candidate_chunks(
        document_id=args.document_id,
        embedding_model=settings.openai_embedding_model,
        force=args.force,
    )

    if args.dry_run:
        print(f"Active DB chunks: {len(active_chunk_ids)}")
        print(f"Embedding candidates: {len(candidates)}")
        if args.sync_delete_stale:
            collection = get_evidence_collection()
            where = {"embedding_model": settings.openai_embedding_model}
            if args.document_id:
                where = {"$and": [where, {"document_id": args.document_id}]}
            result = collection.get(where=where, include=["metadatas"])
            stale_count = len([chunk_id for chunk_id in result.get("ids", []) if chunk_id not in active_chunk_ids])
            print(f"Stale Chroma embeddings: {stale_count}")
        return

    client = EmbeddingClient()
    processed = 0
    for batch in batched(candidates, args.batch_size):
        embeddings = await client.embed_texts([row["chunk_text"] for row in batch])
        await upsert_embeddings(batch, embeddings, client)
        processed += len(batch)
        print(f"Embedded {processed}/{len(candidates)} chunks")

    deleted = 0
    if args.sync_delete_stale:
        deleted = delete_stale_embeddings(
            active_chunk_ids=active_chunk_ids,
            document_id=args.document_id,
            embedding_model=settings.openai_embedding_model,
        )

    print(f"Imported Chroma evidence chunk embeddings: {processed}")
    if args.sync_delete_stale:
        print(f"Deleted stale Chroma embeddings: {deleted}")


if __name__ == "__main__":
    asyncio.run(main())
