"""검진 결과 PDF 다운로드 API.

검진 결과는 evaluate 성공 시 Redis에 10분만 임시 저장된다. PDF 요청은 해당 결과를
다시 계산하지 않아 LLM 호출·DB 쓰기·파일 저장을 발생시키지 않는다.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from app.api.analysis_sessions import get_analysis_session_detail
from app.domain.analysis_report_cache import load_analysis_result
from app.domain.analysis_report_pdf import render_analysis_report_pdf
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/v1/analysis-sessions", tags=["reports"])
logger = logging.getLogger(__name__)


class ReportPdfErrorResponse(ApiResponse):
    result: None = None


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ReportPdfErrorResponse(isSuccess=False, code=code, message=message).model_dump(),
    )


def _filename(service_name: str, session_id: str) -> str:
    # 헤더 인젝션·파일 경로 문자를 제거하고 한글 파일명은 RFC 5987 filename*으로 전달한다.
    safe_name = re.sub(r'[\\/:*?"<>|\r\n]+', "_", service_name).strip() or session_id
    return f"PREP_아이디어검진_{safe_name}_{datetime.now():%Y-%m-%d}.pdf"


@router.get(
    "/{session_id}/report.pdf",
    response_model=None,
    response_class=Response,
    responses={
        404: {"model": ReportPdfErrorResponse},
        409: {"model": ReportPdfErrorResponse},
        500: {"model": ReportPdfErrorResponse},
    },
    summary="아이디어 검진 리포트 PDF 다운로드",
)
async def download_analysis_report_pdf(session_id: str) -> Response | JSONResponse:
    # cache만 보고 409를 반환하면 이미 삭제된 세션도 "결과 만료"로 오인된다. 먼저 세션과
    # health-data 상태를 확인해 기존 분석 API와 같은 404/409 계약을 유지한다.
    session_response = await get_analysis_session_detail(session_id)
    if isinstance(session_response, JSONResponse):
        return session_response
    if not session_response.result.health_data_items:
        return _error(409, "HEALTH_DATA_REQUIRED", "등록된 검진 데이터가 없습니다. 먼저 health-data를 등록해주세요.")

    report = await load_analysis_result(session_id)
    if report is None:
        return _error(
            409,
            "ANALYSIS_RESULT_REQUIRED",
            "검진 결과가 없거나 보관 시간이 만료되었습니다. 다시 검진한 후 PDF를 다운로드해주세요.",
        )

    try:
        pdf = render_analysis_report_pdf(report)
    except Exception:
        logger.exception("Failed to render analysis report PDF")
        return _error(500, "REPORT_PDF_GENERATION_FAILED", "리포트 PDF 생성 중 오류가 발생했습니다.")

    filename = _filename(session_response.result.service_name, session_id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=PREP_report_{session_id}.pdf; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-store",
        },
    )
