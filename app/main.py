import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

# human_review의 Postgres 체크포인터(psycopg 비동기)가 Windows 기본 ProactorEventLoop를
# 거부한다("Psycopg cannot use the 'ProactorEventLoop' to run in async mode") — 로컬 개발
# 환경(Windows)에서만 필요하고, 배포 환경(Linux)은 기본이 이미 SelectorEventLoop라 영향 없다.
# uvicorn이 이벤트루프를 만들기 전에(모듈 임포트 시점) 정책을 바꿔야 적용된다.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.analysis_sessions import router as analysis_sessions_router
from app.api.business_model import router as business_model_router
from app.api.category_classifier import router as category_classifier_router
from app.api.evaluate import router as evaluate_router
from app.api.feasibility import router as feasibility_router
from app.api.funding import router as funding_router
from app.api.judgement import router as judgement_router
from app.api.proposals import router as proposals_router
from app.api.rag import router as rag_router
from app.api.rule_documents import router as rule_documents_router
from app.core.config import settings
from app.core.redis_client import redis_client
from app.db.session import engine
from app.pipeline.checkpointer import close_checkpointer, init_checkpointer


@asynccontextmanager
async def lifespan(app: FastAPI):
    # human_review의 interrupt/resume 상태 영속화용 커넥션 풀 — 검수가 몇 시간 뒤에
    # 재개돼도 같은 풀을 써야 해서 앱 생애주기 동안 하나만 연다.
    await init_checkpointer()
    yield
    await close_checkpointer()
    await redis_client.aclose()
    await engine.dispose()


app = FastAPI(
    title="PREP API",
    lifespan=lifespan,
)
# 프로덕션 FE 도메인은 환경변수로 관리한다. 인증이 없는 MVP API라
# allow_credentials는 쓰지 않고, 기본값은 PREP 프로덕션/FE Vercel 도메인 + 로컬 개발 서버다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_origin_regex=settings.cors_allow_origin_regex or None,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(analysis_sessions_router)
app.include_router(business_model_router)
app.include_router(category_classifier_router)
app.include_router(evaluate_router)
app.include_router(feasibility_router)
app.include_router(funding_router)
app.include_router(judgement_router)
app.include_router(proposals_router)
app.include_router(rag_router)
app.include_router(rule_documents_router)


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
