from __future__ import annotations

import hashlib
from collections.abc import Iterable

from app.core.config import settings


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def to_pgvector_literal(values: Iterable[float]) -> str:
    return "[" + ",".join(f"{value:.10f}" for value in values) + "]"


class EmbeddingClient:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        resolved_api_key = api_key if api_key is not None else settings.openai_api_key
        if not resolved_api_key:
            raise RuntimeError("OPENAI_API_KEY is required to generate embeddings.")

        from openai import AsyncOpenAI

        self.model = model or settings.openai_embedding_model
        self.dimensions = settings.openai_embedding_dimensions
        self.client = AsyncOpenAI(api_key=resolved_api_key)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        response = await self.client.embeddings.create(
            model=self.model,
            input=texts,
            dimensions=self.dimensions,
        )
        return [item.embedding for item in response.data]

    async def embed_query(self, query: str) -> list[float]:
        embeddings = await self.embed_texts([query])
        return embeddings[0]
