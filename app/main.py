from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.analysis_sessions import router as analysis_sessions_router
from app.api.business_model import router as business_model_router
from app.api.category_classifier import router as category_classifier_router
from app.api.evaluate import router as evaluate_router
from app.api.feasibility import router as feasibility_router
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
# 인증이 없는 API(토큰/쿠키 미사용)라 credentials 위험 없이 전체 허용 — 프론트 배포
# 도메인이 정해지면 그때 allow_origins를 좁힌다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(analysis_sessions_router)
app.include_router(business_model_router)
app.include_router(category_classifier_router)
app.include_router(evaluate_router)
app.include_router(feasibility_router)
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
