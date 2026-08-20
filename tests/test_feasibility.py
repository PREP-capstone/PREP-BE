"""데이터 확보 가능성 판단 API 회귀 테스트. 이슈 #38.

data_difficulty/collection_difficulty/data_sensitivity/api_catalog/public_data_catalog
전부 시드 데이터가 필요해 DB 접속을 요구한다.
"""

import pytest
from sqlalchemy import delete

from app.api.analysis_sessions import (
    AnalysisSession,
    CreateAnalysisSessionRequest,
    HealthDataUpsertRequest,
    create_analysis_session,
    create_health_data,
)
from app.api.feasibility import (
    FeasibilityRequest,
    _risk_level_for_score,
    _tokens_overlap_with_name,
    assess_data_feasibility,
)
from app.db.session import AsyncSessionLocal
from app.schemas.common import HealthDataItemInput


def test_risk_level_thresholds_match_design_doc() -> None:
    # db_구축_설계서.md §3.4 — 1~3 쉬움/낮음, 4~10 보통/중간, 12~30 어려움/높음.
    assert _risk_level_for_score(1) == "낮음"
    assert _risk_level_for_score(3) == "낮음"
    assert _risk_level_for_score(4) == "중간"
    assert _risk_level_for_score(10) == "중간"
    assert _risk_level_for_score(12) == "높음"
    assert _risk_level_for_score(30) == "높음"


def test_tokens_overlap_matches_compound_word_against_short_catalog_token() -> None:
    # 회귀: "공복혈당"(item name)이 카탈로그의 짧은 토큰 "혈당"과 방향이 반대라
    # 안 걸리던 문제 — 토큰 단위 양방향 비교로 잡아야 한다.
    assert _tokens_overlap_with_name("걸음수, 심박수, 수면, 혈당 등", "공복혈당")
    assert not _tokens_overlap_with_name("걸음수, 심박수, 수면 등", "공복혈당")
    assert not _tokens_overlap_with_name(None, "공복혈당")


async def _create_session(name: str = "feasibility-test") -> str:
    request = CreateAnalysisSessionRequest(service_name=name, service_description="d")
    response = await create_analysis_session(request)
    return response.result.session_id


async def _delete_session(session_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(delete(AnalysisSession).where(AnalysisSession.session_id == session_id))
        await session.commit()


@pytest.mark.db
async def test_data_feasibility_score_takes_max_across_items_not_sum() -> None:
    """생체지표×수동입력(3)과 라이프스타일×기기연동(4) 중 최댓값(4)만 채택 — 합산 아님.

    "심박수"는 BIOMARKER_EXTRA 소속이라 gate_keywords 시드 여부와 무관하게 항상
    생체지표로 분류된다(위 institution_sync 테스트와 같은 이유).
    """
    session_id = await _create_session()
    try:
        request = HealthDataUpsertRequest(
            health_data_items=[
                HealthDataItemInput(name="심박수", data_type="numeric", source="user_input"),
                HealthDataItemInput(name="걸음수", data_type="numeric", source="device_sync"),
            ]
        )
        await create_health_data(session_id, request)

        result = await assess_data_feasibility(FeasibilityRequest(session_id=session_id))

        assert result.result.data_feasibility_score == 4
        assert result.result.risk_level == "중간"
    finally:
        await _delete_session(session_id)


@pytest.mark.db
async def test_institution_sync_reaches_highest_difficulty_tier() -> None:
    """기관연동(S=10) × 생체지표(D=3) = 30, 최고 등급(높음)까지 실제로 도달하는지 확인 —
    institution_sync를 추가하기 전에는 이 조합 자체가 구조적으로 불가능했다.

    "심박수"는 BIOMARKER_EXTRA(하드코딩) 소속이라 gate_keywords 시드 여부와 무관하게
    항상 생체지표로 분류된다 — gate_keywords는 룰 추출 파이프라인 산출물이라 이
    테스트 환경(단순 참조표 seed)에는 없다.
    """
    session_id = await _create_session()
    try:
        request = HealthDataUpsertRequest(
            health_data_items=[
                HealthDataItemInput(name="심박수", data_type="numeric", source="institution_sync"),
            ]
        )
        await create_health_data(session_id, request)

        result = await assess_data_feasibility(FeasibilityRequest(session_id=session_id))

        assert result.result.data_feasibility_score == 30
        assert result.result.risk_level == "높음"
    finally:
        await _delete_session(session_id)


@pytest.mark.db
async def test_privacy_risks_matched_by_item_code_only() -> None:
    """item_code가 없는 항목은 매칭 대상에서 빠지고(에러 아님), 있는 항목만 정확 매칭된다."""
    session_id = await _create_session()
    try:
        request = HealthDataUpsertRequest(
            health_data_items=[
                HealthDataItemInput(
                    name="복용약물", data_type="text", source="user_input", item_code="sensitive_004"
                ),
                HealthDataItemInput(name="메모", data_type="text", source="user_input"),
            ]
        )
        await create_health_data(session_id, request)

        result = await assess_data_feasibility(FeasibilityRequest(session_id=session_id))

        risk_names = [r.data_name for r in result.result.privacy_risks]
        assert risk_names == ["복용약물"]
    finally:
        await _delete_session(session_id)


@pytest.mark.db
async def test_returns_404_for_unknown_session() -> None:
    response = await assess_data_feasibility(FeasibilityRequest(session_id="no_such_session"))

    assert response.status_code == 404


@pytest.mark.db
async def test_returns_409_when_no_health_data_registered() -> None:
    session_id = await _create_session()
    try:
        response = await assess_data_feasibility(FeasibilityRequest(session_id=session_id))

        assert response.status_code == 409
    finally:
        await _delete_session(session_id)
