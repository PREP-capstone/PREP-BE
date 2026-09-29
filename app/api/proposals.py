"""제안서 자동 작성 API (이슈 #102, docs/제안서_자동작성_API_명세서.md).

app/api/funding.py(PR #101)와 동일한 컨벤션을 따른다 -- UploadFile+Form, 10MB 제한,
_error() 헬퍼, ApiResponse envelope. 검진 리포트 PDF를 텍스트로 추출하는 부분은 지금
funding.py와 중복 구현이다 -- app/domain/pdf_utils.py 같은 공유 모듈 분리는 funding
담당과 협의 후 별도 진행 (§6-3).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pypdf import PdfReader
from sqlalchemy import select

from app.core.redis_client import redis_client
from app.db.models import ProposalFieldDefinition, ProposalTemplateFieldMap
from app.db.session import AsyncSessionLocal
from app.domain.proposal_docx import render_proposal_docx
from app.domain.proposal_llm import (
    ALWAYS_BLANK_FIELDS,
    ATTACHMENT_CHECKLISTS,
    ProposalLLMUnavailable,
    generate_missing_sections,
)
from app.domain.proposal_pdf import render_proposal_pdf
from app.domain.proposal_sections import merge_custom_fields
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/v1/proposals", tags=["proposals"])

logger = logging.getLogger(__name__)

_MAX_REPORT_BYTES = 10 * 1024 * 1024
_PROPOSAL_TTL_SECONDS = 600
_CACHE_KEY_PREFIX = "proposal:"
_PROPOSAL_JOB_TTL_SECONDS = 1800
_JOB_KEY_PREFIX = "proposal_job:"
TEMPLATE_TYPES = frozenset({"PSST", "RND", "IR"})

# ProposalSection/CompleteSection이 공통으로 쓰는 값 타입 -- field_type에 따라 셋 중 하나.
# TEXT -> str, CHECKLIST -> list[str], TABLE -> list[dict]
SectionValue = str | list[str] | list[dict]


class ProposalErrorResponse(ApiResponse):
    result: None = None


async def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ProposalErrorResponse(isSuccess=False, code=code, message=message).model_dump(),
    )


def _is_pdf(file: UploadFile) -> bool:
    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()
    return filename.endswith(".pdf") or content_type == "application/pdf"


def _extract_pdf_text(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# ---------------------------------------------------------------------------
# GET /field-definitions
# ---------------------------------------------------------------------------


class FieldDefinitionItem(BaseModel):
    field_key: str
    category: str
    label: str
    description: str | None
    field_type: str
    requirement: str
    display_order: int


class FieldDefinitionsResult(BaseModel):
    template_type: str
    fields: list[FieldDefinitionItem]


class FieldDefinitionsResponse(ApiResponse):
    result: FieldDefinitionsResult


async def _fetch_field_definitions(template_type: str) -> list[FieldDefinitionItem]:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(
                    ProposalFieldDefinition.field_key,
                    ProposalFieldDefinition.category,
                    ProposalFieldDefinition.label,
                    ProposalFieldDefinition.description,
                    ProposalFieldDefinition.field_type,
                    ProposalFieldDefinition.display_order,
                    ProposalTemplateFieldMap.requirement,
                )
                .join(
                    ProposalTemplateFieldMap,
                    ProposalTemplateFieldMap.field_key == ProposalFieldDefinition.field_key,
                )
                .where(ProposalTemplateFieldMap.template_type == template_type)
                .order_by(ProposalFieldDefinition.display_order)
            )
        ).all()

    return [
        FieldDefinitionItem(
            field_key=row.field_key,
            category=row.category,
            label=row.label,
            description=row.description,
            field_type=row.field_type,
            requirement=row.requirement,
            display_order=row.display_order,
        )
        for row in rows
    ]


@router.get(
    "/field-definitions",
    response_model=FieldDefinitionsResponse,
    responses={400: {"model": ProposalErrorResponse}},
)
async def get_field_definitions(template_type: str) -> FieldDefinitionsResponse | JSONResponse:
    if template_type not in TEMPLATE_TYPES:
        return await _error(
            400,
            "PROPOSAL_TEMPLATE_TYPE_INVALID",
            f"template_type은 {sorted(TEMPLATE_TYPES)} 중 하나여야 합니다.",
        )

    fields = await _fetch_field_definitions(template_type)
    return FieldDefinitionsResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공",
        result=FieldDefinitionsResult(template_type=template_type, fields=fields),
    )


# ---------------------------------------------------------------------------
# POST /generate
# ---------------------------------------------------------------------------


class ProposalSection(BaseModel):
    field_key: str
    label: str
    field_type: str
    value: SectionValue


class GenerateResult(BaseModel):
    proposal_id: str
    template_type: str
    # "ok" | "unavailable" -- LLM 호출 실패 시에도 요청 전체를 502로 죽이지 않고
    # (§10.1 원칙) 자리표시자로 채운 뒤 이 값으로 프론트에 알린다.
    llm_status: str
    sections: list[ProposalSection]


class GenerateResponse(ApiResponse):
    result: GenerateResult


class ProposalJobResult(BaseModel):
    job_id: str
    status: str
    template_type: str
    proposal_id: str | None = None
    llm_status: str | None = None
    sections: list[ProposalSection] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class ProposalJobResponse(ApiResponse):
    result: ProposalJobResult


def _job_key(job_id: str) -> str:
    return _JOB_KEY_PREFIX + job_id


async def _save_job(job: ProposalJobResult) -> None:
    await redis_client.set(
        _job_key(job.job_id),
        json.dumps(job.model_dump(mode="json"), ensure_ascii=False),
        ex=_PROPOSAL_JOB_TTL_SECONDS,
    )


async def _load_job(job_id: str) -> ProposalJobResult | None:
    cached = await redis_client.get(_job_key(job_id))
    if cached is None:
        return None
    return ProposalJobResult.model_validate(json.loads(cached))


def _placeholder_value(field_type: str, label: str) -> SectionValue:
    if field_type == "TABLE":
        return []
    return f"[자동 생성 실패 -- 직접 입력해주세요: {label}]"


async def _build_generated_result(
    template_type: str,
    report_text: str,
    values: dict,
    proposal_id: str,
) -> GenerateResult:
    fields = await _fetch_field_definitions(template_type)

    sections: list[ProposalSection] = []
    llm_target_fields: list[dict] = []

    for field in fields:
        user_value = values.get(field.field_key)
        if isinstance(user_value, (str, list)) and user_value:
            sections.append(
                ProposalSection(
                    field_key=field.field_key, label=field.label, field_type=field.field_type, value=user_value
                )
            )
            continue

        if field.field_type == "CHECKLIST":
            sections.append(
                ProposalSection(
                    field_key=field.field_key,
                    label=field.label,
                    field_type=field.field_type,
                    value=ATTACHMENT_CHECKLISTS.get(template_type, []),
                )
            )
            continue

        if field.field_key in ALWAYS_BLANK_FIELDS:
            sections.append(
                ProposalSection(
                    field_key=field.field_key,
                    label=field.label,
                    field_type=field.field_type,
                    value=[] if field.field_type == "TABLE" else "",
                )
            )
            continue

        llm_target_fields.append(
            {
                "field_key": field.field_key,
                "label": field.label,
                "field_type": field.field_type,
                "description": field.description,
            }
        )

    llm_status = "ok"
    generated: dict = {}
    if llm_target_fields:
        try:
            generated = await generate_missing_sections(template_type, report_text, values, llm_target_fields)
        except ProposalLLMUnavailable:
            llm_status = "unavailable"

    for field_spec in llm_target_fields:
        key = field_spec["field_key"]
        value = generated.get(key, _placeholder_value(field_spec["field_type"], field_spec["label"]))
        sections.append(
            ProposalSection(
                field_key=key, label=field_spec["label"], field_type=field_spec["field_type"], value=value
            )
        )

    order = {field.field_key: field.display_order for field in fields}
    sections.sort(key=lambda section: order.get(section.field_key, 0))
    return GenerateResult(
        proposal_id=proposal_id,
        template_type=template_type,
        llm_status=llm_status,
        sections=sections,
    )


@router.post(
    "/generate",
    response_model=GenerateResponse,
    responses={
        400: {"model": ProposalErrorResponse},
        413: {"model": ProposalErrorResponse},
    },
)
async def generate_proposal(
    report: Annotated[UploadFile, File(description="PREP 아이디어 검진 리포트 PDF")],
    template_type: Annotated[str, Form(description="PSST / RND / IR")],
    field_values: Annotated[str, Form(description="사용자가 채운 필드값(JSON 문자열)")] = "{}",
) -> GenerateResponse | JSONResponse:
    if template_type not in TEMPLATE_TYPES:
        return await _error(
            400,
            "PROPOSAL_TEMPLATE_TYPE_INVALID",
            f"template_type은 {sorted(TEMPLATE_TYPES)} 중 하나여야 합니다.",
        )

    if not _is_pdf(report):
        return await _error(400, "PROPOSAL_REPORT_PDF_REQUIRED", "PDF 파일만 업로드할 수 있습니다.")

    content = await report.read()
    if len(content) > _MAX_REPORT_BYTES:
        return await _error(413, "PROPOSAL_REPORT_TOO_LARGE", "리포트 PDF는 10MB 이하만 업로드할 수 있습니다.")

    try:
        values = json.loads(field_values) if field_values else {}
    except json.JSONDecodeError:
        return await _error(400, "PROPOSAL_FIELD_VALUES_INVALID", "field_values는 올바른 JSON 문자열이어야 합니다.")
    if not isinstance(values, dict):
        return await _error(400, "PROPOSAL_FIELD_VALUES_INVALID", "field_values JSON은 객체여야 합니다.")

    report_text = _extract_pdf_text(content)
    result = await _build_generated_result(template_type, report_text, values, str(uuid.uuid4()))

    # 완료(POST /{id}/complete) 전까지는 캐시하지 않는다 (§0, §5.2) -- 재요청 시 매번 새로 생성.
    # (generate_missing_sections() 내부의 짧은 캐시는 "완료 전 재시도 비용 절감"용으로 별개다.)
    return GenerateResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공",
        result=result,
    )


async def _run_proposal_generation_job(
    job: ProposalJobResult,
    content: bytes,
    values: dict,
) -> None:
    """인프로세스 백그라운드에서 실행되는 생성 작업.

    작업 상태와 완료 결과는 Redis에 저장하므로 프론트는 요청 타임아웃 없이 polling할
    수 있다. 현재는 별도 worker 없이 단일 API 컨테이너에서 실행하는 MVP 구조이며,
    프로세스 재시작 중인 작업은 TTL 만료/재요청으로 처리한다.
    """
    try:
        job.status = "processing"
        job.updated_at = datetime.now(timezone.utc)
        await _save_job(job)

        report_text = _extract_pdf_text(content)
        result = await _build_generated_result(job.template_type, report_text, values, str(uuid.uuid4()))
        job.status = "completed"
        job.proposal_id = result.proposal_id
        job.llm_status = result.llm_status
        job.sections = result.sections
        job.updated_at = datetime.now(timezone.utc)
        await _save_job(job)
    except ProposalLLMUnavailable as error:
        job.status = "failed"
        job.error_code = "PROPOSAL_LLM_UNAVAILABLE"
        job.error_message = str(error)
        job.updated_at = datetime.now(timezone.utc)
        await _save_job(job)
    except Exception:
        logger.exception("proposal generation job failed: job_id=%s", job.job_id)
        job.status = "failed"
        job.error_code = "PROPOSAL_GENERATION_FAILED"
        job.error_message = "제안서 초안 생성 중 오류가 발생했습니다. 다시 시도해주세요."
        job.updated_at = datetime.now(timezone.utc)
        await _save_job(job)


@router.post(
    "/generate/async",
    response_model=ProposalJobResponse,
    status_code=202,
    responses={
        400: {"model": ProposalErrorResponse},
        413: {"model": ProposalErrorResponse},
        503: {"model": ProposalErrorResponse},
    },
)
async def generate_proposal_async(
    background_tasks: BackgroundTasks,
    report: Annotated[UploadFile, File(description="PREP 아이디어 검진 리포트 PDF")],
    template_type: Annotated[str, Form(description="PSST / RND / IR")],
    field_values: Annotated[str, Form(description="사용자가 채운 필드값(JSON 문자열)")] = "{}",
) -> ProposalJobResponse | JSONResponse:
    """PDF 검증 후 즉시 작업 ID를 반환하고 초안 생성은 백그라운드에서 수행한다."""
    if template_type not in TEMPLATE_TYPES:
        return await _error(
            400,
            "PROPOSAL_TEMPLATE_TYPE_INVALID",
            f"template_type은 {sorted(TEMPLATE_TYPES)} 중 하나여야 합니다.",
        )
    if not _is_pdf(report):
        return await _error(400, "PROPOSAL_REPORT_PDF_REQUIRED", "PDF 파일만 업로드할 수 있습니다.")

    content = await report.read()
    if len(content) > _MAX_REPORT_BYTES:
        return await _error(413, "PROPOSAL_REPORT_TOO_LARGE", "리포트 PDF는 10MB 이하만 업로드할 수 있습니다.")
    try:
        values = json.loads(field_values) if field_values else {}
    except json.JSONDecodeError:
        return await _error(400, "PROPOSAL_FIELD_VALUES_INVALID", "field_values는 올바른 JSON 문자열이어야 합니다.")
    if not isinstance(values, dict):
        return await _error(400, "PROPOSAL_FIELD_VALUES_INVALID", "field_values JSON은 객체여야 합니다.")

    now = datetime.now(timezone.utc)
    job = ProposalJobResult(
        job_id=str(uuid.uuid4()),
        status="pending",
        template_type=template_type,
        created_at=now,
        updated_at=now,
    )
    try:
        await _save_job(job)
    except Exception:
        logger.exception("proposal generation job could not be persisted: job_id=%s", job.job_id)
        return await _error(503, "PROPOSAL_JOB_UNAVAILABLE", "제안서 생성 작업을 시작할 수 없습니다.")

    background_tasks.add_task(_run_proposal_generation_job, job, content, values)
    return ProposalJobResponse(
        isSuccess=True,
        code="PROPOSAL_GENERATION_ACCEPTED",
        message="제안서 초안 생성 작업을 접수했습니다.",
        result=job,
    )


@router.get(
    "/generate/jobs/{job_id}",
    response_model=ProposalJobResponse,
    responses={404: {"model": ProposalErrorResponse}},
)
async def get_proposal_generation_job(job_id: str) -> ProposalJobResponse | JSONResponse:
    job = await _load_job(job_id)
    if job is None:
        return await _error(404, "PROPOSAL_JOB_NOT_FOUND", "제안서 생성 작업을 찾을 수 없거나 만료되었습니다.")
    return ProposalJobResponse(
        isSuccess=True,
        code="PROPOSAL_GENERATION_STATUS_FOUND",
        message="제안서 생성 작업 상태를 조회했습니다.",
        result=job,
    )


# ---------------------------------------------------------------------------
# POST /{proposal_id}/complete, GET /{proposal_id}/pdf
# ---------------------------------------------------------------------------


class CompleteSection(BaseModel):
    field_key: str
    value: SectionValue


class CustomField(BaseModel):
    """proposal_field_definitions에 등록된 고정 field_key가 없는 자유 서술형 추가
    항목 (프론트 요청 v6, 2026-09-11 -- 요청 1). category는 자유 문자열로 받는다 --
    프론트는 5개 카테고리(일반현황/문제인식/성장전략/팀구성/RND특화)에서만 버튼을
    노출하지만, 스키마 자체에 값 제한을 걸지 않는다(요청 원문 그대로)."""

    category: str
    label: str
    value: str


class CompleteRequest(BaseModel):
    template_type: str  # render_proposal_pdf()가 문서 제목을 고르는 데 필요
    sections: list[CompleteSection]
    custom_fields: list[CustomField] = []


class CompleteResult(BaseModel):
    proposal_id: str
    expires_at: datetime


class CompleteResponse(ApiResponse):
    result: CompleteResult


@router.post(
    "/{proposal_id}/complete",
    response_model=CompleteResponse,
    responses={400: {"model": ProposalErrorResponse}},
)
async def complete_proposal(proposal_id: str, request: CompleteRequest) -> CompleteResponse | JSONResponse:
    """"완료" 또는 "PDF 저장하기" 클릭 시 호출 -- 둘 다 동일 트리거로 취급한다(§0).

    이 시점부터 Redis TTL 10분이 시작된다. TTL 만료 후에는 GET .../pdf가
    PROPOSAL_NOT_FOUND(404)를 반환한다 -- Redis가 자동으로 지우므로 별도 삭제 API는 없다.

    프론트는 field_key와 value만 보낸다. PDF 렌더링에 필요한 label/field_type은
    proposal_field_definitions에서 서버가 직접 조회한다 -- 프론트가 다시 실어보낼 필요도
    없고, 잘못된 field_type을 실어보내 PDF 렌더링이 깨지는 것도 막는다(리뷰 중 D-*).
    """
    if request.template_type not in TEMPLATE_TYPES:
        return await _error(
            400,
            "PROPOSAL_TEMPLATE_TYPE_INVALID",
            f"template_type은 {sorted(TEMPLATE_TYPES)} 중 하나여야 합니다.",
        )

    field_keys = [section.field_key for section in request.sections]
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(
                    ProposalFieldDefinition.field_key,
                    ProposalFieldDefinition.label,
                    ProposalFieldDefinition.field_type,
                    ProposalFieldDefinition.category,
                ).where(ProposalFieldDefinition.field_key.in_(field_keys))
            )
        ).all()
    meta = {row.field_key: (row.label, row.field_type, row.category) for row in rows}

    unknown = [key for key in field_keys if key not in meta]
    if unknown:
        return await _error(
            400,
            "PROPOSAL_FIELD_KEY_INVALID",
            f"알 수 없는 field_key입니다: {unknown}",
        )

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=_PROPOSAL_TTL_SECONDS)
    payload = {
        "proposal_id": proposal_id,
        "template_type": request.template_type,
        "sections": [
            {
                "field_key": section.field_key,
                "label": meta[section.field_key][0],
                "field_type": meta[section.field_key][1],
                # PDF/Word 렌더링 시 custom_fields를 해당 category 섹션 끝에 끼워
                # 넣으려면(app/domain/proposal_sections.py) 어느 category인지 알아야
                # 한다 -- 프론트 요청 v6(2026-09-11, 요청 1)로 추가.
                "category": meta[section.field_key][2],
                "value": section.value,
            }
            for section in request.sections
        ],
        "custom_fields": [custom_field.model_dump() for custom_field in request.custom_fields],
        "expires_at": expires_at.isoformat(),
    }
    await redis_client.set(
        _CACHE_KEY_PREFIX + proposal_id, json.dumps(payload, ensure_ascii=False), ex=_PROPOSAL_TTL_SECONDS
    )

    return CompleteResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공",
        result=CompleteResult(proposal_id=proposal_id, expires_at=expires_at),
    )


@router.get(
    "/{proposal_id}/pdf",
    response_model=None,  # Response(실제 PDF 바이너리)와 JSONResponse(에러)를 함께 반환 -- 둘 다 pydantic 필드가 아니라 응답모델 추론을 꺼야 한다
    responses={
        404: {"model": ProposalErrorResponse},
        200: {"content": {"application/pdf": {}}},
    },
)
async def get_proposal_pdf(proposal_id: str) -> Response | JSONResponse:
    """10분 이내에만 다운로드 가능. `complete` 호출 전이면 404.

    실제 PDF 바이너리(app/domain/proposal_pdf.py, 나눔고딕 임베딩)를 반환한다.
    """
    cached = await redis_client.get(_CACHE_KEY_PREFIX + proposal_id)
    if cached is None:
        return await _error(404, "PROPOSAL_NOT_FOUND", "제안서를 찾을 수 없거나 만료되었습니다.")

    payload = json.loads(cached)
    sections = merge_custom_fields(payload["sections"], payload.get("custom_fields", []))
    pdf_bytes = render_proposal_pdf(payload["template_type"], sections)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="proposal_{proposal_id}.pdf"'},
    )


@router.get(
    "/{proposal_id}/docx",
    response_model=None,  # get_proposal_pdf와 동일한 이유로 응답모델 추론을 끈다
    responses={
        404: {"model": ProposalErrorResponse},
        200: {
            "content": {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {}
            }
        },
    },
)
async def get_proposal_docx(proposal_id: str) -> Response | JSONResponse:
    """GET /{id}/pdf와 완전히 동일한 인증/캐시/10분 만료 규칙 (프론트 요청 v6,
    2026-09-11 -- 요청 2). 실제 .docx 바이너리(app/domain/proposal_docx.py)를 반환한다.
    """
    cached = await redis_client.get(_CACHE_KEY_PREFIX + proposal_id)
    if cached is None:
        return await _error(404, "PROPOSAL_NOT_FOUND", "제안서를 찾을 수 없거나 만료되었습니다.")

    payload = json.loads(cached)
    sections = merge_custom_fields(payload["sections"], payload.get("custom_fields", []))
    docx_bytes = render_proposal_docx(payload["template_type"], sections)
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="proposal_{proposal_id}.docx"'},
    )
