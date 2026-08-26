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
# 로컬 개발 서버는 포트를 아직 몰라서 정규식으로 허용한다(localhost/127.0.0.1 전 포트).
# TODO: 프론트 배포 도메인 확정되면 allow_origins에 실제 값 채우기(예: "https://실제도메인").
# 인증이 없는 API라 allow_credentials는 안 씀 — 그래서 "*"도 기술적으론 가능하지만,
# 구체적 origin으로 좁혀두는 게 더 안전하다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
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
