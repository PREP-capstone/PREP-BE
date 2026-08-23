import asyncio
import uuid as uuid_module
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import delete, select

from app.api.analysis_sessions import (
    AnalysisSession,
    CreateAnalysisSessionRequest,
    HealthDataItem,
    HealthDataItemInput,
    HealthDataUpsertRequest,
    PatchCategoryRequest,
    PatchHealthDataRequest,
    create_analysis_session,
    create_health_data,
    generate_session_id,
    get_analysis_session_detail,
    update_category,
    update_health_data,
)
from app.db.session import AsyncSessionLocal


def test_create_analysis_session_requires_category_1() -> None:
    with pytest.raises(ValueError):
        CreateAnalysisSessionRequest(service_name="n", service_description="d")


def test_generate_session_id_uses_date_prefix() -> None:
    session_id = generate_session_id(datetime(2026, 8, 18, 9, 30))

    assert session_id.startswith("session_20260818_")
    assert len(session_id) == len("session_20260818_") + 8


async def _create_session(service_name: str = "concurrency-test") -> str:
    request = CreateAnalysisSessionRequest(service_name=service_name, service_description="d", category_1="수면")
    response = await create_analysis_session(request)
    return response.result.session_id


async def _delete_session(session_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(AnalysisSession).where(AnalysisSession.session_id == session_id))
        await session.commit()


def _status_of(result) -> int:
    return getattr(result, "status_code", 200)


@pytest.mark.db
async def test_concurrent_health_data_post_only_one_succeeds() -> None:
    """동시에 들어온 두 POST가 둘 다 '데이터 없음'으로 보고 중복 삽입하는 TOCTOU
    레이스를 lock_analysis_session()의 FOR UPDATE가 막는지 확인한다.
    """
    session_id = await _create_session()
    try:
        request = HealthDataUpsertRequest(
            health_data_items=[HealthDataItemInput(name="hr", data_type="numeric", source="device_sync")]
        )
        results = await asyncio.gather(
            create_health_data(session_id, request),
            create_health_data(session_id, request),
        )

        assert sorted(_status_of(r) for r in results) == [200, 409]

        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(select(HealthDataItem).where(HealthDataItem.session_id == session_id))
            ).scalars().all()
        assert len(rows) == 1
    finally:
        await _delete_session(session_id)


@pytest.mark.db
async def test_create_analysis_session_retries_past_id_collision() -> None:
    """session_id가 이미 존재하는 unique_violation이면 새 id로 재시도해서
    성공해야 한다 — 다른 종류의 IntegrityError와 구분하는 로직의 정상 경로 확인.
    """
    fixed_uuid = uuid_module.uuid4()
    today = datetime.now(timezone.utc)
    colliding_id = f"session_{today:%Y%m%d}_{fixed_uuid.hex[:8]}"

    async with AsyncSessionLocal() as session:
        session.add(
            AnalysisSession(
                session_id=colliding_id,
                service_name="existing",
                service_description="d",
                target_users=[],
                service_type=None,
                processing_purpose=[],
                service_actions=[],
            )
        )
        await session.commit()

    created_ids = [colliding_id]
    try:
        call_count = 0
        real_uuid4 = uuid_module.uuid4

        def fake_uuid4():
            nonlocal call_count
            call_count += 1
            return fixed_uuid if call_count == 1 else real_uuid4()

        with patch("app.api.analysis_sessions.uuid.uuid4", side_effect=fake_uuid4):
            request = CreateAnalysisSessionRequest(service_name="new", service_description="d2", category_1="수면")
            response = await create_analysis_session(request)

        assert response.result.session_id != colliding_id
        created_ids.append(response.result.session_id)
        assert call_count >= 2
    finally:
        for session_id in created_ids:
            await _delete_session(session_id)


@pytest.mark.db
async def test_get_analysis_session_detail_snapshot_not_torn_by_concurrent_patch() -> None:
    """GET이 analysis_session/health_data_items를 잠금 없는 별개 SELECT 두 번으로
    읽는데, REPEATABLE READ로 트랜잭션을 승격해뒀으므로 그 사이에 PATCH가 커밋돼도
    두 SELECT는 트랜잭션 시작 시점의 같은 스냅샷을 봐야 한다(torn read 방지).

    endpoint 함수 자체를 호출하면 두 SELECT 사이에 정확히 멈추게 할 지점이 없어서,
    같은 isolation-level + 2-SELECT 패턴을 직접 재현해 타이밍을 제어한다.
    """
    session_id = await _create_session()
    try:
        create_req = HealthDataUpsertRequest(
            health_data_items=[HealthDataItemInput(name="hr", data_type="numeric", source="device_sync")],
            processing_purpose=["초기목적"],
        )
        await create_health_data(session_id, create_req)

        reached_after_first_read = asyncio.Event()
        patch_done = asyncio.Event()

        async def read_with_pause():
            async with AsyncSessionLocal() as session:
                await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                analysis_session = await session.get(AnalysisSession, session_id)
                reached_after_first_read.set()
                await patch_done.wait()
                result = await session.execute(
                    select(HealthDataItem).where(HealthDataItem.session_id == session_id)
                )
                return analysis_session.processing_purpose, len(result.scalars().all())

        async def concurrent_patch():
            await reached_after_first_read.wait()
            patch_req = PatchHealthDataRequest(
                health_data_items=[
                    HealthDataItemInput(name="hr", data_type="numeric", source="device_sync"),
                    HealthDataItemInput(name="glucose", data_type="numeric", source="device_sync"),
                ],
                processing_purpose=["변경된목적"],
            )
            await update_health_data(session_id, patch_req)
            patch_done.set()

        (processing_purpose, item_count), _ = await asyncio.gather(read_with_pause(), concurrent_patch())

        assert processing_purpose == ["초기목적"]
        assert item_count == 1
    finally:
        await _delete_session(session_id)


@pytest.mark.db
async def test_health_data_round_trip_preserves_item_code() -> None:
    session_id = await _create_session()
    try:
        request = HealthDataUpsertRequest(
            health_data_items=[
                HealthDataItemInput(
                    name="혈당", data_type="numeric", source="device_sync", item_code="sensitive_001"
                )
            ]
        )
        await create_health_data(session_id, request)

        detail = await get_analysis_session_detail(session_id)

        assert detail.result.health_data_items[0].item_code == "sensitive_001"
    finally:
        await _delete_session(session_id)


@pytest.mark.db
async def test_update_category_reflects_classification_result() -> None:
    # market/business-model API가 조회 키로 쓰는 category_1/category_2/target을
    # STEP 1 분류 이후 이 PATCH로 반영한다 — lock_analysis_session 도입(코드
    # 리뷰 반영) 이후에도 정상 갱신되는지 확인.
    session_id = await _create_session()
    try:
        response = await update_category(
            session_id,
            PatchCategoryRequest(category_1="수면", category_2="정보제공", target="전연령"),
        )

        assert response.result.category_1 == "수면"
        assert response.result.category_2 == "정보제공"
        assert response.result.target == "전연령"

        detail = await get_analysis_session_detail(session_id)
        assert detail.result.category_1 == "수면"
    finally:
        await _delete_session(session_id)


@pytest.mark.db
async def test_update_category_returns_404_for_unknown_session() -> None:
    response = await update_category("does-not-exist", PatchCategoryRequest(category_1="수면"))
    assert _status_of(response) == 404
