from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.judgement import router as judgement_router
from app.core.config import settings
from app.core.redis_client import redis_client
from app.db.session import engine
from app.rag.retriever import EvidenceRetriever


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await redis_client.aclose()
    await engine.dispose()


app = FastAPI(
    title="PREP API",
    lifespan=lifespan,
)
app.include_router(judgement_router)


class RagSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    tag_regulatory: bool | None = None
    tag_privacy: bool | None = None
    tag_advertising: bool | None = None
    document_ids: list[str] | None = None


class RagSearchResult(BaseModel):
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


@app.get("/api/v1/health")
async def health_check():
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))

    await redis_client.ping()

    return {
        "status": "ok",
        "postgres": "ok",
        "redis": "ok",
    }


@app.post("/api/v1/rag/search", response_model=list[RagSearchResult])
async def search_rag_evidence(request: RagSearchRequest):
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")

    retriever = EvidenceRetriever()
    return await retriever.search(
        request.query,
        top_k=request.top_k,
        tag_regulatory=request.tag_regulatory,
        tag_privacy=request.tag_privacy,
        tag_advertising=request.tag_advertising,
        document_ids=request.document_ids,
    )
