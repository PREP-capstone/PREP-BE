from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.db.models.analysis_session import AnalysisSession, HealthDataItem
from app.db.session import AsyncSessionLocal
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/v1/analysis-sessions", tags=["analysis-sessions"])

_MAX_LIST_LENGTH = 50
_MAX_STRING_ITEM_LENGTH = 200


def _validate_string_lengths(values: list[str] | None) -> list[str] | None:
    if values is None:
        return values
    for value in values:
        if len(value) > _MAX_STRING_ITEM_LENGTH:
            raise ValueError(f"항목 길이는 {_MAX_STRING_ITEM_LENGTH}자를 넘을 수 없습니다.")
    return values


class HealthDataItemInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    data_type: str = Field(min_length=1, max_length=50)
    unit: str | None = Field(default=None, max_length=50)
    source: Literal["user_input", "device_sync", "os_sync"]
    is_sensitive: bool = False


class HealthDataItemResponse(BaseModel):
    """요청(HealthDataItemInput)과 필드가 지금은 같지만, 상속시키지 않고 독립적으로
    정의한다 — 상속하면 나중에 요청 전용 필드가 추가될 때 응답에도 조용히 새어나간다.
    """

    name: str
    data_type: str
    unit: str | None
    source: Literal["user_input", "device_sync", "os_sync"]
    is_sensitive: bool


class CreateAnalysisSessionRequest(BaseModel):
    service_name: str = Field(min_length=1, max_length=200)
    service_description: str = Field(min_length=1, max_length=5000)
    target_users: list[str] = Field(default_factory=list, max_length=_MAX_LIST_LENGTH)
    service_type: str | None = Field(default=None, max_length=50)

    @field_validator("target_users")
    @classmethod
    def _cap_target_user_length(cls, value: list[str]) -> list[str]:
        return _validate_string_lengths(value)


class CreateAnalysisSessionResult(BaseModel):
    session_id: str
    service_name: str
    created_at: datetime


class CreateAnalysisSessionResponse(ApiResponse):
    result: CreateAnalysisSessionResult


class HealthDataUpsertRequest(BaseModel):
    health_data_items: list[HealthDataItemInput] = Field(default_factory=list, max_length=_MAX_LIST_LENGTH)
    processing_purpose: list[str] | None = Field(default=None, max_length=_MAX_LIST_LENGTH)
    service_actions: list[str] | None = Field(default=None, max_length=_MAX_LIST_LENGTH)

    @field_validator("processing_purpose", "service_actions")
    @classmethod
    def _cap_item_length(cls, value: list[str] | None) -> list[str] | None:
        return _validate_string_lengths(value)


class PatchHealthDataRequest(BaseModel):
    health_data_items: list[HealthDataItemInput] | None = Field(default=None, max_length=_MAX_LIST_LENGTH)
    processing_purpose: list[str] | None = Field(default=None, max_length=_MAX_LIST_LENGTH)
    service_actions: list[str] | None = Field(default=None, max_length=_MAX_LIST_LENGTH)

    @field_validator("processing_purpose", "service_actions")
    @classmethod
    def _cap_item_length(cls, value: list[str] | None) -> list[str] | None:
        return _validate_string_lengths(value)


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
    # DB의 created_at/updated_at은 전부 UTC(DateTime(timezone=True) + func.now())라서
    # 로컬 시스템 시간을 쓰면 서버가 UTC가 아닐 때 날짜 prefix가 어긋난다.
    current = now or datetime.now(timezone.utc)
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


_SESSION_ID_RETRY_ATTEMPTS = 3


@router.post(
    "",
    response_model=CreateAnalysisSessionResponse,
    responses={409: {"model": AnalysisSessionErrorResponse}},
)
async def create_analysis_session(
    request: CreateAnalysisSessionRequest,
) -> CreateAnalysisSessionResponse | JSONResponse:
    async with AsyncSessionLocal() as session:
        for attempt in range(_SESSION_ID_RETRY_ATTEMPTS):
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
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                if attempt == _SESSION_ID_RETRY_ATTEMPTS - 1:
                    return JSONResponse(
                        status_code=409,
                        content=AnalysisSessionErrorResponse(
                            isSuccess=False,
                            code="ANALYSIS_SESSION_ID_CONFLICT",
                            message="세션 ID 생성에 실패했습니다. 다시 시도해주세요.",
                        ).model_dump(),
                    )
                continue
            await session.refresh(analysis_session)
            break

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
    responses={404: {"model": AnalysisSessionErrorResponse}, 409: {"model": AnalysisSessionErrorResponse}},
)
async def create_health_data(
    session_id: str, request: HealthDataUpsertRequest
) -> HealthDataMutationResponse | JSONResponse:
    async with AsyncSessionLocal() as session:
        # FOR UPDATE로 세션 row를 잠가서, 동시에 들어온 두 요청이 둘 다 "데이터 없음"으로
        # 보고 중복 삽입하는 TOCTOU 레이스를 막는다 — 나중 트랜잭션은 앞 트랜잭션이
        # commit할 때까지 이 SELECT에서 블록되고, 그 뒤엔 existing이 채워져 409로 빠진다.
        analysis_session = (
            await session.execute(
                select(AnalysisSession).where(AnalysisSession.session_id == session_id).with_for_update()
            )
        ).scalar_one_or_none()
        if analysis_session is None:
            return not_found_response()

        existing = (
            await session.execute(
                select(HealthDataItem.health_data_item_id)
                .where(HealthDataItem.session_id == session_id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return JSONResponse(
                status_code=409,
                content=AnalysisSessionErrorResponse(
                    isSuccess=False,
                    code="HEALTH_DATA_ALREADY_EXISTS",
                    message="이미 등록된 검진 데이터가 있습니다. 수정은 PATCH를 사용하세요.",
                ).model_dump(),
            )

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
        # POST와 동일하게 FOR UPDATE로 잠근다 — 락 없이 delete+insert만 하면 동시 PATCH가
        # 서로의 uncommitted 변경을 못 보고 중복/겹치는 row를 남길 수 있다.
        analysis_session = (
            await session.execute(
                select(AnalysisSession).where(AnalysisSession.session_id == session_id).with_for_update()
            )
        ).scalar_one_or_none()
        if analysis_session is None:
            return not_found_response()

        if request.health_data_items is not None:
            await replace_health_data_items(session, session_id, request.health_data_items)
            health_data_count = len(request.health_data_items)
            # replace_health_data_items만으로는 analysis_session row가 dirty로 표시되지
            # 않아 updated_at의 onupdate가 안 걸린다 — 명시적으로 찍어준다.
            analysis_session.updated_at = datetime.now(timezone.utc)
        else:
            count_result = await session.execute(
                select(HealthDataItem.health_data_item_id).where(HealthDataItem.session_id == session_id)
            )
            health_data_count = len(count_result.scalars().all())
        if request.processing_purpose is not None:
            analysis_session.processing_purpose = request.processing_purpose
        if request.service_actions is not None:
            analysis_session.service_actions = request.service_actions

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
