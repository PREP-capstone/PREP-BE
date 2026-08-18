from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.db.models.analysis_session import AnalysisSession, HealthDataItem
from app.db.session import AsyncSessionLocal
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/v1/analysis-sessions", tags=["analysis-sessions"])


class HealthDataItemInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    data_type: str = Field(min_length=1, max_length=50)
    unit: str | None = Field(default=None, max_length=50)
    source: str = Field(min_length=1, max_length=50)
    is_sensitive: bool = False


class HealthDataItemResponse(HealthDataItemInput):
    pass


class CreateAnalysisSessionRequest(BaseModel):
    service_name: str = Field(min_length=1, max_length=200)
    service_description: str = Field(min_length=1)
    target_users: list[str] = Field(default_factory=list)
    service_type: str | None = Field(default=None, max_length=50)


class CreateAnalysisSessionResult(BaseModel):
    session_id: str
    service_name: str
    created_at: datetime


class CreateAnalysisSessionResponse(ApiResponse):
    result: CreateAnalysisSessionResult


class HealthDataUpsertRequest(BaseModel):
    health_data_items: list[HealthDataItemInput] = Field(default_factory=list)
    processing_purpose: list[str] | None = None
    service_actions: list[str] | None = None


class PatchHealthDataRequest(BaseModel):
    health_data_items: list[HealthDataItemInput] | None = None
    processing_purpose: list[str] | None = None
    service_actions: list[str] | None = None


class HealthDataMutationResult(BaseModel):
    session_id: str
    health_data_count: int


class HealthDataMutationResponse(ApiResponse):
    result: HealthDataMutationResult


class AnalysisSessionDetail(BaseModel):
    session_id: str
    service_name: str
    service_description: str
    target_users: list[str]
    service_type: str | None
    health_data_items: list[HealthDataItemResponse]
    processing_purpose: list[str]
    service_actions: list[str]


class AnalysisSessionDetailResponse(ApiResponse):
    result: AnalysisSessionDetail


class AnalysisSessionErrorResponse(ApiResponse):
    result: None = None


def generate_session_id(now: datetime | None = None) -> str:
    current = now or datetime.now()
    return f"session_{current:%Y%m%d}_{uuid.uuid4().hex[:8]}"


def not_found_response() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=AnalysisSessionErrorResponse(
            isSuccess=False,
            code="ANALYSIS_SESSION_NOT_FOUND",
            message="분석 세션을 찾을 수 없습니다.",
        ).model_dump(),
    )


def health_data_item_to_response(item: HealthDataItem) -> HealthDataItemResponse:
    return HealthDataItemResponse(
        name=item.name,
        data_type=item.data_type,
        unit=item.unit,
        source=item.source,
        is_sensitive=item.is_sensitive,
    )


async def replace_health_data_items(session, session_id: str, items: list[HealthDataItemInput]) -> None:
    await session.execute(delete(HealthDataItem).where(HealthDataItem.session_id == session_id))
    session.add_all([
        HealthDataItem(
            session_id=session_id,
            name=item.name,
            data_type=item.data_type,
            unit=item.unit,
            source=item.source,
            is_sensitive=item.is_sensitive,
            sort_order=index,
        )
        for index, item in enumerate(items)
    ])



@router.post("", response_model=CreateAnalysisSessionResponse)
async def create_analysis_session(request: CreateAnalysisSessionRequest) -> CreateAnalysisSessionResponse:
    async with AsyncSessionLocal() as session:
        analysis_session = AnalysisSession(
            session_id=generate_session_id(),
            service_name=request.service_name,
            service_description=request.service_description,
            target_users=request.target_users,
            service_type=request.service_type,
            processing_purpose=[],
            service_actions=[],
        )
        session.add(analysis_session)
        await session.commit()
        await session.refresh(analysis_session)

    return CreateAnalysisSessionResponse(
        isSuccess=True,
        code="ANALYSIS_SESSION_CREATED",
        message="분석 세션이 생성되었습니다.",
        result=CreateAnalysisSessionResult(
            session_id=analysis_session.session_id,
            service_name=analysis_session.service_name,
            created_at=analysis_session.created_at,
        ),
    )


@router.get(
    "/{session_id}",
    response_model=AnalysisSessionDetailResponse,
    responses={404: {"model": AnalysisSessionErrorResponse}},
)
async def get_analysis_session_detail(session_id: str) -> AnalysisSessionDetailResponse | JSONResponse:
    async with AsyncSessionLocal() as session:
        analysis_session = await session.get(AnalysisSession, session_id)
        if analysis_session is None:
            return not_found_response()

        result = await session.execute(
            select(HealthDataItem)
            .where(HealthDataItem.session_id == session_id)
            .order_by(HealthDataItem.sort_order, HealthDataItem.created_at)
        )
        health_data_items = result.scalars().all()

    return AnalysisSessionDetailResponse(
        isSuccess=True,
        code="ANALYSIS_SESSION_FOUND",
        message="분석 세션을 조회했습니다.",
        result=AnalysisSessionDetail(
            session_id=analysis_session.session_id,
            service_name=analysis_session.service_name,
            service_description=analysis_session.service_description,
            target_users=analysis_session.target_users,
            service_type=analysis_session.service_type,
            health_data_items=[health_data_item_to_response(item) for item in health_data_items],
            processing_purpose=analysis_session.processing_purpose,
            service_actions=analysis_session.service_actions,
        ),
    )


@router.post(
    "/{session_id}/health-data",
    response_model=HealthDataMutationResponse,
    responses={404: {"model": AnalysisSessionErrorResponse}},
)
async def create_health_data(
    session_id: str, request: HealthDataUpsertRequest
) -> HealthDataMutationResponse | JSONResponse:
    async with AsyncSessionLocal() as session:
        analysis_session = await session.get(AnalysisSession, session_id)
        if analysis_session is None:
            return not_found_response()

        await replace_health_data_items(session, session_id, request.health_data_items)
        analysis_session.processing_purpose = request.processing_purpose or []
        analysis_session.service_actions = request.service_actions or []
        await session.commit()

    return HealthDataMutationResponse(
        isSuccess=True,
        code="HEALTH_DATA_CREATED",
        message="검진 데이터가 등록되었습니다.",
        result=HealthDataMutationResult(
            session_id=session_id,
            health_data_count=len(request.health_data_items),
        ),
    )


@router.patch(
    "/{session_id}/health-data",
    response_model=HealthDataMutationResponse,
    responses={404: {"model": AnalysisSessionErrorResponse}},
)
async def update_health_data(
    session_id: str, request: PatchHealthDataRequest
) -> HealthDataMutationResponse | JSONResponse:
    async with AsyncSessionLocal() as session:
        analysis_session = await session.get(AnalysisSession, session_id)
        if analysis_session is None:
            return not_found_response()

        if request.health_data_items is not None:
            await replace_health_data_items(session, session_id, request.health_data_items)
        if request.processing_purpose is not None:
            analysis_session.processing_purpose = request.processing_purpose
        if request.service_actions is not None:
            analysis_session.service_actions = request.service_actions

        count_result = await session.execute(
            select(HealthDataItem.health_data_item_id).where(HealthDataItem.session_id == session_id)
        )
        health_data_count = len(count_result.scalars().all())
        await session.commit()

    return HealthDataMutationResponse(
        isSuccess=True,
        code="HEALTH_DATA_UPDATED",
        message="검진 데이터가 수정되었습니다.",
        result=HealthDataMutationResult(
            session_id=session_id,
            health_data_count=health_data_count,
        ),
    )
