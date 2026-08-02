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
from app.rag.embeddings import EmbeddingClient, content_hash, to_pgvector_literal


SELECT_CANDIDATES_SQL = """
SELECT
    ec.chunk_id,
    ec.chunk_text,
    ece.content_hash AS existing_content_hash
FROM evidence_chunks ec
JOIN evidence_documents ed ON ed.document_id = ec.document_id
LEFT JOIN evidence_chunk_embeddings ece
    ON ece.chunk_id = ec.chunk_id
    AND ece.embedding_model = :embedding_model
WHERE ec.status = 'active'
  AND ed.status = 'active'
  AND ed.usage_scope IN ('RAG', 'BOTH')
  {document_filter}
ORDER BY ec.document_id, ec.chunk_order
"""


UPSERT_EMBEDDING_SQL = """
INSERT INTO evidence_chunk_embeddings (
    chunk_id,
    embedding_model,
    embedding_dimensions,
    content_hash,
    embedding,
    embedded_at,
    created_at,
    updated_at
) VALUES (
    :chunk_id,
    :embedding_model,
    :embedding_dimensions,
    :content_hash,
    CAST(:embedding AS vector),
    now(),
    now(),
    now()
)
ON CONFLICT (chunk_id) DO UPDATE SET
    embedding_model = EXCLUDED.embedding_model,
    embedding_dimensions = EXCLUDED.embedding_dimensions,
    content_hash = EXCLUDED.content_hash,
    embedding = EXCLUDED.embedding,
    embedded_at = now(),
    updated_at = now()
"""


def batched[T](items: list[T], size: int) -> list[list[T]]:
    return [items[index:index + size] for index in range(0, len(items), size)]


async def load_candidate_chunks(document_id: str | None, embedding_model: str, force: bool) -> list[dict]:
    document_filter = "AND ec.document_id = :document_id" if document_id else ""
    query = SELECT_CANDIDATES_SQL.format(document_filter=document_filter)
    params = {"embedding_model": embedding_model}
    if document_id:
        params["document_id"] = document_id

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                text(query),
                params,
            )
        ).mappings().all()

    candidates: list[dict] = []
    for row in rows:
        row_hash = content_hash(row["chunk_text"])
        if force or row["existing_content_hash"] != row_hash:
            candidates.append({
                "chunk_id": row["chunk_id"],
                "chunk_text": row["chunk_text"],
                "content_hash": row_hash,
            })
    return candidates


async def upsert_embeddings(rows: list[dict], embeddings: list[list[float]], client: EmbeddingClient) -> None:
    async with AsyncSessionLocal() as session:
        for row, embedding in zip(rows, embeddings, strict=True):
            await session.execute(
                text(UPSERT_EMBEDDING_SQL),
                {
                    "chunk_id": row["chunk_id"],
                    "embedding_model": client.model,
                    "embedding_dimensions": client.dimensions,
                    "content_hash": row["content_hash"],
                    "embedding": to_pgvector_literal(embedding),
                },
            )
        await session.commit()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Generate pgvector embeddings for evidence_chunks.")
    parser.add_argument("--document-id", help="Embed one evidence document only.")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--force", action="store_true", help="Regenerate embeddings even if text hash matches.")
    parser.add_argument("--dry-run", action="store_true", help="List candidate count without OpenAI calls.")
    args = parser.parse_args()

    candidates = await load_candidate_chunks(
        document_id=args.document_id,
        embedding_model=settings.openai_embedding_model,
        force=args.force,
    )

    if args.dry_run:
        print(f"Embedding candidates: {len(candidates)}")
        return

    client = EmbeddingClient()
    processed = 0
    for batch in batched(candidates, args.batch_size):
        embeddings = await client.embed_texts([row["chunk_text"] for row in batch])
        await upsert_embeddings(batch, embeddings, client)
        processed += len(batch)
        print(f"Embedded {processed}/{len(candidates)} chunks")

    print(f"Imported evidence_chunk_embeddings: {processed}")


if __name__ == "__main__":
    asyncio.run(main())
