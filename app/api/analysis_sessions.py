from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db.models.analysis_session import AnalysisSession, HealthDataItem
from app.db.session import AsyncSessionLocal
from app.schemas.common import ApiResponse, HealthDataItemInput

router = APIRouter(prefix="/api/v1/analysis-sessions", tags=["analysis-sessions"])

_MAX_LIST_LENGTH = 50
_MAX_STRING_ITEM_LENGTH = 200
_UNIQUE_VIOLATION_SQLSTATE = "23505"
_LOCK_TIMEOUT = "5s"

# 문자열 리스트 항목 하나하나의 길이도 제한한다 — 리스트 개수(max_length=_MAX_LIST_LENGTH)만
# 제한하면 항목 1개에 수 MB 텍스트를 넣는 것까지는 못 막는다.
_BoundedStr = Annotated[str, StringConstraints(max_length=_MAX_STRING_ITEM_LENGTH)]


def _is_unique_violation(error: IntegrityError) -> bool:
    return getattr(error.orig, "sqlstate", None) == _UNIQUE_VIOLATION_SQLSTATE


class HealthDataItemResponse(BaseModel):
    """요청(HealthDataItemInput)과 필드가 지금은 같지만, 상속시키지 않고 독립적으로
    정의한다 — 상속하면 나중에 요청 전용 필드가 추가될 때 응답에도 조용히 새어나간다.
    """

    name: str
    data_type: str
    unit: str | None
    source: Literal["user_input", "device_sync", "os_sync"]
    is_sensitive: bool
    item_code: str | None


class CreateAnalysisSessionRequest(BaseModel):
    service_name: str = Field(min_length=1, max_length=200)
    service_description: str = Field(min_length=1, max_length=5000)
    target_users: list[_BoundedStr] = Field(default_factory=list, max_length=_MAX_LIST_LENGTH)
    service_type: str | None = Field(default=None, max_length=50)


class CreateAnalysisSessionResult(BaseModel):
    session_id: str
    service_name: str
    created_at: datetime


class CreateAnalysisSessionResponse(ApiResponse):
    result: CreateAnalysisSessionResult


class HealthDataUpsertRequest(BaseModel):
    # min_length=1(기본값 없음, 필수) — 빈 리스트를 허용하면 이미 데이터가 등록된
    # 세션에 health_data_items: []로 다시 POST해도 "데이터 없음" 체크를 매번 통과해
    # 중복 제출 방지(409)가 무력화되고 processing_purpose/service_actions가
    # PATCH 없이 조용히 덮어써진다.
    health_data_items: list[HealthDataItemInput] = Field(min_length=1, max_length=_MAX_LIST_LENGTH)
    processing_purpose: list[_BoundedStr] | None = Field(default=None, max_length=_MAX_LIST_LENGTH)
    service_actions: list[_BoundedStr] | None = Field(default=None, max_length=_MAX_LIST_LENGTH)


class PatchHealthDataRequest(BaseModel):
    health_data_items: list[HealthDataItemInput] | None = Field(default=None, max_length=_MAX_LIST_LENGTH)
    processing_purpose: list[_BoundedStr] | None = Field(default=None, max_length=_MAX_LIST_LENGTH)
    service_actions: list[_BoundedStr] | None = Field(default=None, max_length=_MAX_LIST_LENGTH)


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


def locked_response() -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content=AnalysisSessionErrorResponse(
            isSuccess=False,
            code="ANALYSIS_SESSION_LOCKED",
            message="다른 요청이 이 세션을 처리 중입니다. 잠시 후 다시 시도해주세요.",
        ).model_dump(),
    )


async def lock_analysis_session(session, session_id: str) -> AnalysisSession | None:
    """analysis_session row를 FOR UPDATE로 잠근다.

    lock_timeout 없이 무기한 대기하면, 락을 쥔 커넥션이 죽었을 때 이 작은 커넥션
    풀을 공유하는 judgement.py의 무관한 엔드포인트까지 연쇄로 멈출 수 있다. 타임아웃
    초과 시 OperationalError가 올라오므로 호출부에서 locked_response()로 받는다.
    """
    await session.execute(text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
    return (
        await session.execute(
            select(AnalysisSession).where(AnalysisSession.session_id == session_id).with_for_update()
        )
    ).scalar_one_or_none()


def health_data_item_to_response(item: HealthDataItem) -> HealthDataItemResponse:
    return HealthDataItemResponse(
        name=item.name,
        data_type=item.data_type,
        unit=item.unit,
        source=item.source,
        is_sensitive=item.is_sensitive,
        item_code=item.item_code,
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
            item_code=item.item_code,
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
    # created_at을 서버 기본값(server_default=func.now())에 맡기고 commit 뒤 refresh()로
    # 읽어오면, commit은 성공했는데 refresh()만 커넥션 문제로 실패하는 경우 클라이언트는
    # 500(생성 실패)으로 보고 재시도해서 고아 세션이 남을 수 있다. session_id 생성에 쓴
    # 시각을 그대로 created_at에도 넣어서 refresh 자체를 없앤다.
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        for attempt in range(_SESSION_ID_RETRY_ATTEMPTS):
            analysis_session = AnalysisSession(
                session_id=generate_session_id(now),
                service_name=request.service_name,
                service_description=request.service_description,
                target_users=request.target_users,
                service_type=request.service_type,
                processing_purpose=[],
                service_actions=[],
                created_at=now,
            )
            session.add(analysis_session)
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                # unique_violation(23505)이 아니면 session_id 충돌이 아닌 다른 제약
                # 위반이다 — 새 session_id로 재시도해도 고쳐지지 않으므로 원인을 감추지
                # 않고 그대로 올려보낸다.
                if not _is_unique_violation(error):
                    raise
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
        # analysis_session과 health_data_items를 별개 SELECT 두 번으로 읽는다. 기본
        # READ COMMITTED면 그 사이에 PATCH가 커밋될 때 "옛 processing_purpose/
        # service_actions + 새 health_data_items"처럼 앞뒤가 안 맞는 스냅샷을 반환할
        # 수 있어, REPEATABLE READ로 트랜잭션 시작 시점 스냅샷을 고정한다.
        await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})

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
        # 세션 row를 잠가서, 동시에 들어온 두 요청이 둘 다 "데이터 없음"으로 보고
        # 중복 삽입하는 TOCTOU 레이스를 막는다 — 나중 트랜잭션은 앞 트랜잭션이 commit할
        # 때까지 블록되고, 그 뒤엔 existing이 채워져 409로 빠진다.
        try:
            analysis_session = await lock_analysis_session(session, session_id)
        except OperationalError:
            return locked_response()
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
    responses={404: {"model": AnalysisSessionErrorResponse}, 409: {"model": AnalysisSessionErrorResponse}},
)
async def update_health_data(
    session_id: str, request: PatchHealthDataRequest
) -> HealthDataMutationResponse | JSONResponse:
    async with AsyncSessionLocal() as session:
        # POST와 동일하게 잠근다 — 락 없이 delete+insert만 하면 동시 PATCH가 서로의
        # uncommitted 변경을 못 보고 중복/겹치는 row를 남길 수 있다.
        try:
            analysis_session = await lock_analysis_session(session, session_id)
        except OperationalError:
            return locked_response()
        if analysis_session is None:
            return not_found_response()

        if request.health_data_items is not None:
            await replace_health_data_items(session, session_id, request.health_data_items)
            health_data_count = len(request.health_data_items)
            # replace_health_data_items만으로는 analysis_session row가 dirty로 표시되지
            # 않아 updated_at의 onupdate가 안 걸린다 — 명시적으로 찍어준다.
            analysis_session.updated_at = datetime.now(timezone.utc)
        else:
            health_data_count = (
                await session.execute(
                    select(func.count())
                    .select_from(HealthDataItem)
                    .where(HealthDataItem.session_id == session_id)
                )
            ).scalar_one()
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
