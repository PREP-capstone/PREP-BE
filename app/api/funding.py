from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pypdf import PdfReader
from sqlalchemy import select

from app.domain.funding_match import (
    FundingProgram,
    FundingProfile,
    extract_funding_profile,
    funding_profile_from_session,
    is_money_support_program,
    profile_to_dict,
    score_funding_program,
    sort_funding_matches,
)
from app.domain.funding_sources import fetch_external_funding_programs
from app.db.models import AnalysisSession, HealthDataItem
from app.db.session import AsyncSessionLocal
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/v1/funding", tags=["funding"])

_MAX_REPORT_BYTES = 10 * 1024 * 1024
_SERVICE_TIMEZONE = ZoneInfo("Asia/Seoul")


class FundingProgramRecommendation(BaseModel):
    program_id: str
    title: str
    match_score: int
    matched_reasons: list[str]
    deadline: date | None
    days_left: int | None
    max_amount: int | None
    support_amount_text: str | None
    region: str | None
    stage: str | None
    source: str | None
    source_url: str | None
    description: str | None
    keywords: list[str]


class FundingRecommendationsResult(BaseModel):
    total: int
    recommended_at: datetime
    basis_date: date
    sort_order: list[str]
    extracted_profile: dict
    sources: list[str]
    source_warnings: list[str]
    recommendations: list[FundingProgramRecommendation]


class FundingRecommendationsResponse(ApiResponse):
    result: FundingRecommendationsResult


class FundingErrorResponse(ApiResponse):
    result: None = None


class SessionFundingRecommendationRequest(BaseModel):
    session_id: str
    region: str | None = None
    startup_stage: str | None = None
    keywords: list[str] = Field(default_factory=list, max_length=30)
    top_k: int = Field(default=12, ge=1, le=50)


async def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=FundingErrorResponse(isSuccess=False, code=code, message=message).model_dump(),
    )


@router.post(
    "/recommendations",
    response_model=FundingRecommendationsResponse,
    responses={
        400: {"model": FundingErrorResponse},
        413: {"model": FundingErrorResponse},
        422: {"model": FundingErrorResponse},
    },
)
async def recommend_funding_programs(
    file: Annotated[UploadFile, File(description="PREP 아이디어 검진 리포트 PDF")],
    region: Annotated[str | None, Form(description="지역 필터/가중치 보정값")] = None,
    startup_stage: Annotated[str | None, Form(description="사업 단계 필터/가중치 보정값")] = None,
    keywords: Annotated[str | None, Form(description="쉼표로 구분한 추가 키워드")] = None,
    top_k: Annotated[int, Form(ge=1, le=50)] = 12,
):
    if not _is_pdf(file):
        return await _error(400, "FUNDING_REPORT_PDF_REQUIRED", "PDF 파일만 업로드할 수 있습니다.")

    content = await file.read()
    if len(content) > _MAX_REPORT_BYTES:
        return await _error(413, "FUNDING_REPORT_TOO_LARGE", "리포트 PDF는 10MB 이하만 업로드할 수 있습니다.")

    report_text = _extract_pdf_text(content)
    if len(report_text.strip()) < 20:
        return await _error(422, "FUNDING_REPORT_TEXT_EMPTY", "PDF에서 분석 가능한 텍스트를 추출하지 못했습니다.")

    profile = extract_funding_profile(
        report_text,
        region=region,
        startup_stage=startup_stage,
        keywords=keywords,
    )
    return await _recommend_from_profile(profile, top_k)


@router.post(
    "/recommendations/from-session",
    response_model=FundingRecommendationsResponse,
    responses={404: {"model": FundingErrorResponse}},
)
async def recommend_funding_programs_from_session(
    request: SessionFundingRecommendationRequest,
):
    async with AsyncSessionLocal() as session:
        analysis_session = await session.get(AnalysisSession, request.session_id)
        if analysis_session is None:
            return await _error(404, "ANALYSIS_SESSION_NOT_FOUND", "분석 세션을 찾을 수 없습니다.")
        health_data_names = list(
            (
                await session.execute(
                    select(HealthDataItem.name).where(HealthDataItem.session_id == request.session_id)
                )
            ).scalars()
        )
        profile = funding_profile_from_session(
            service_name=analysis_session.service_name,
            service_description=analysis_session.service_description,
            target_users=analysis_session.target_users,
            service_type=analysis_session.service_type,
            category_1=analysis_session.category_1,
            category_2=analysis_session.category_2,
            target=analysis_session.target,
            health_data_names=health_data_names,
            region=request.region,
            startup_stage=request.startup_stage,
            keywords=request.keywords,
        )

    return await _recommend_from_profile(profile, request.top_k)


async def _recommend_from_profile(profile: FundingProfile, top_k: int) -> FundingRecommendationsResponse:
    recommended_at = datetime.now(_SERVICE_TIMEZONE)
    today = recommended_at.date()

    rows, source_warnings = await fetch_external_funding_programs(profile)
    active_rows = [
        row
        for row in rows
        if (row.deadline is None or row.deadline >= today) and is_money_support_program(row)
    ]

    matches = sort_funding_matches(
        [
            match
            for match in (score_funding_program(row, profile, today) for row in active_rows)
            if match.match_score > 0
        ]
    )
    recommendations = [
        _to_recommendation(match.program, match.match_score, match.matched_reasons, match.days_left)
        for match in matches[:top_k]
    ]

    return FundingRecommendationsResponse(
        isSuccess=True,
        code="FUNDING_RECOMMENDATIONS_FOUND",
        message="지원사업 추천 결과를 조회했습니다.",
        result=FundingRecommendationsResult(
            total=len(recommendations),
            recommended_at=recommended_at,
            basis_date=today,
            sort_order=["match_score_desc", "deadline_asc", "max_amount_desc"],
            extracted_profile=profile_to_dict(profile),
            sources=sorted({row.source for row in rows if row.source}),
            source_warnings=source_warnings,
            recommendations=recommendations,
        ),
    )


def _is_pdf(file: UploadFile) -> bool:
    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()
    return filename.endswith(".pdf") or content_type == "application/pdf"


def _extract_pdf_text(content: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


def _to_recommendation(
    program: FundingProgram,
    match_score: int,
    matched_reasons: list[str],
    days_left: int | None,
) -> FundingProgramRecommendation:
    return FundingProgramRecommendation(
        program_id=program.program_id,
        title=program.title,
        match_score=match_score,
        matched_reasons=matched_reasons,
        deadline=program.deadline,
        days_left=days_left,
        max_amount=program.max_amount,
        support_amount_text=program.support_amount_text,
        region=program.region,
        stage=program.stage,
        source=program.source,
        source_url=program.source_url,
        description=program.description,
        keywords=program.keywords or [],
    )
