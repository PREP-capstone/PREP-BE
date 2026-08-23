"""카테고리 분류(STEP 1) 추론 API. 작업 #7 부속 — 3번 담당 API가 조회 키로 쓰는
category_1/category_2를 채우기 위해 필요했으나, 분류 자체는 세션 소유(2번 담당)가
아니라 별도 모델(app/domain/category_classifier.py)이 담당한다.

이 API는 세션을 건드리지 않는다 — 순수 추론만 하고, 결과 반영은 호출한 쪽이
PATCH /api/v1/analysis-sessions/{session_id}/category로 별도 수행한다(2026-08-22
팀 결정 — 분류 호출 시점과 세션 반영 시점을 분리해 프론트/파이프라인이 자유롭게
오케스트레이션할 수 있게 한다).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.domain.category_classifier import CategoryModelUnavailable, predict_categories
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/v1/category-classifier", tags=["category-classifier"])


class CategoryClassifyRequest(BaseModel):
    service_description: str = Field(min_length=1, max_length=5000)


class CategoryClassifyResult(BaseModel):
    category_1: str
    category_1_confidence: float
    category_2: str
    category_2_confidence: float


class CategoryClassifyResponse(ApiResponse):
    result: CategoryClassifyResult


class CategoryClassifyErrorResponse(ApiResponse):
    result: None = None


@router.post(
    "/predict",
    response_model=CategoryClassifyResponse,
    responses={503: {"model": CategoryClassifyErrorResponse}},
)
async def predict_category(request: CategoryClassifyRequest) -> CategoryClassifyResponse | JSONResponse:
    try:
        # CPU 추론이라 이벤트 루프를 막지 않도록 스레드로 넘긴다 — 다른 요청(DB
        # 조회 위주)이 대기 중이면 blocking 호출 하나가 전체 서버를 멈춰세운다.
        (category_1, category_1_confidence), (category_2, category_2_confidence) = await asyncio.to_thread(
            predict_categories, request.service_description
        )
    except CategoryModelUnavailable:
        return JSONResponse(
            status_code=503,
            content=CategoryClassifyErrorResponse(
                isSuccess=False,
                code="CATEGORY_MODEL_UNAVAILABLE",
                message="카테고리 분류 모델을 사용할 수 없습니다.",
            ).model_dump(),
        )

    return CategoryClassifyResponse(
        isSuccess=True,
        code="CATEGORY_CLASSIFIED",
        message="카테고리 분류가 완료되었습니다.",
        result=CategoryClassifyResult(
            category_1=category_1,
            category_1_confidence=category_1_confidence,
            category_2=category_2,
            category_2_confidence=category_2_confidence,
        ),
    )
