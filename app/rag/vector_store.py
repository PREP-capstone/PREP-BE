from __future__ import annotations

from functools import lru_cache

from app.core.config import settings


@lru_cache(maxsize=1)
def get_evidence_collection():
    """Return the persistent Chroma collection for evidence chunks."""

    import chromadb

    client = chromadb.PersistentClient(path=settings.chroma_persist_directory)
    return client.get_or_create_collection(
        name=settings.chroma_collection_name,
        metadata={"hnsw:space": "cosine"},
    )
