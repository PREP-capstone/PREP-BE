from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.api.analysis_sessions import router as analysis_sessions_router

from app.api.judgement import router as judgement_router
from app.api.rag import router as rag_router
from app.core.redis_client import redis_client
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await redis_client.aclose()
    await engine.dispose()


app = FastAPI(
    title="PREP API",
    lifespan=lifespan,
)
app.include_router(analysis_sessions_router)
app.include_router(judgement_router)
app.include_router(rag_router)


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
