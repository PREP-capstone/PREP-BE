"""제안서 자동 작성 API (이슈 #102, docs/제안서_자동작성_API_명세서.md).

app/api/funding.py(PR #101)와 동일한 컨벤션을 따른다 -- UploadFile+Form, 10MB 제한,
_error() 헬퍼, ApiResponse envelope. 검진 리포트 PDF를 텍스트로 추출하는 부분은 지금
funding.py와 중복 구현이다 -- app/domain/pdf_utils.py 같은 공유 모듈 분리는 funding
담당과 협의 후 별도 진행 (§6-3).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, File, Form, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pypdf import PdfReader
from sqlalchemy import select

from app.core.redis_client import redis_client
from app.db.models import ProposalFieldDefinition, ProposalTemplateFieldMap
from app.db.session import AsyncSessionLocal
from app.domain.proposal_llm import (
    ATTACHMENT_CHECKLISTS,
    ProposalLLMUnavailable,
    generate_missing_sections,
)
from app.domain.proposal_pdf import render_proposal_pdf
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/api/v1/proposals", tags=["proposals"])

_MAX_REPORT_BYTES = 10 * 1024 * 1024
_PROPOSAL_TTL_SECONDS = 600
_CACHE_KEY_PREFIX = "proposal:"
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


def _placeholder_value(field_type: str, label: str) -> SectionValue:
    if field_type == "TABLE":
        return []
    return f"[자동 생성 실패 -- 직접 입력해주세요: {label}]"


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

    report_text = _extract_pdf_text(content)
    fields = await _fetch_field_definitions(template_type)

    sections: list[ProposalSection] = []
    llm_target_fields: list[dict] = []  # generate_missing_sections()에 넘길 스펙만 추림

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
        if key in generated:
            value: SectionValue = generated[key]
        else:
            value = _placeholder_value(field_spec["field_type"], field_spec["label"])
        sections.append(
            ProposalSection(
                field_key=key, label=field_spec["label"], field_type=field_spec["field_type"], value=value
            )
        )

    order = {field.field_key: field.display_order for field in fields}
    sections.sort(key=lambda section: order.get(section.field_key, 0))

    # 완료(POST /{id}/complete) 전까지는 캐시하지 않는다 (§0, §5.2) -- 재요청 시 매번 새로 생성.
    # (generate_missing_sections() 내부의 짧은 캐시는 "완료 전 재시도 비용 절감"용으로 별개다.)
    return GenerateResponse(
        isSuccess=True,
        code="COMMON200",
        message="성공",
        result=GenerateResult(
            proposal_id=str(uuid.uuid4()), template_type=template_type, llm_status=llm_status, sections=sections
        ),
    )


# ---------------------------------------------------------------------------
# POST /{proposal_id}/complete, GET /{proposal_id}/pdf
# ---------------------------------------------------------------------------


class CompleteSection(BaseModel):
    field_key: str
    value: SectionValue


class CompleteRequest(BaseModel):
    template_type: str  # render_proposal_pdf()가 문서 제목을 고르는 데 필요
    sections: list[CompleteSection]


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
                ).where(ProposalFieldDefinition.field_key.in_(field_keys))
            )
        ).all()
    meta = {row.field_key: (row.label, row.field_type) for row in rows}

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
                "value": section.value,
            }
            for section in request.sections
        ],
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
    pdf_bytes = render_proposal_pdf(payload["template_type"], payload["sections"])
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="proposal_{proposal_id}.pdf"'},
    )
