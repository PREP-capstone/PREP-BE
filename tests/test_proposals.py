"""제안서 자동 작성 API/LLM/PDF 테스트 (이슈 #102). DB/네트워크 불필요 -- 전부 mock.

field-definitions 실제 DB 조회 1건만 @pytest.mark.db로 표시한다
(`scripts/seed_proposal_fields.py` 실행 후 로컬에서 확인).
"""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile
from pypdf import PdfReader
from starlette.datastructures import Headers

from docx import Document

from app.api import proposals
from app.api.proposals import (
    CompleteRequest,
    CompleteSection,
    CustomField,
    _extract_pdf_text,
    _is_pdf,
    _placeholder_value,
    complete_proposal,
    get_field_definitions,
    get_proposal_docx,
    get_proposal_pdf,
)
from app.domain import proposal_llm
from app.domain.proposal_docx import render_proposal_docx
from app.domain.proposal_llm import (
    ATTACHMENT_CHECKLISTS,
    TABLE_ITEM_SCHEMAS,
    ProposalLLMUnavailable,
    _SYSTEM_PROMPT_TEMPLATE,
    build_response_schema,
    generate_missing_sections,
)
from app.domain.proposal_pdf import render_proposal_pdf
from app.domain.proposal_sections import merge_custom_fields
from scripts.seed_proposal_fields import (
    FIELD_DEFINITION_ROWS,
    TEMPLATE_FIELD_ROWS,
    TEMPLATE_TYPES,
)


def _upload_file(filename: str, content_type: str) -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(b"dummy"), headers=Headers({"content-type": content_type}))


def _fake_openai_response(content: str):
    message = MagicMock(content=content)
    choice = MagicMock(message=message)
    return MagicMock(choices=[choice])


def _patched_client(response_content: str):
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=_fake_openai_response(response_content))
    return patch("app.domain.proposal_llm.AsyncOpenAI", return_value=mock_client)


def _font_is_embedded(pdf_bytes: bytes, font_base_name: str) -> bool:
    """PDF를 이미지로 렌더링해서 눈으로 확인하는 대신, 폰트가 실제로 파일 안에 박혀
    있는지(/FontFile2)를 구조적으로 확인한다 -- 한 번은 실제로 이미지를 렌더링해서
    CID 폰트 버전이 한글을 빈 칸으로 그리는 것을 직접 확인했고(app/domain/proposal_pdf.py
    docstring 참고), 그 회귀를 이후로도 값싸게 계속 잡기 위한 자동 검사다.
    """
    reader = PdfReader(BytesIO(pdf_bytes))
    for page in reader.pages:
        fonts = (page.get("/Resources") or {}).get("/Font") or {}
        for font_ref in fonts.values():
            font_obj = font_ref.get_object()
            if font_base_name not in str(font_obj.get("/BaseFont", "")):
                continue
            descriptor = font_obj.get("/FontDescriptor")
            if descriptor is not None and "/FontFile2" in descriptor.get_object():
                return True
    return False


# ---------------------------------------------------------------------------
# 필드 매트릭스 데이터 자체의 정합성 (DB 불필요 -- CI에서 실행)
# ---------------------------------------------------------------------------


def test_field_definition_keys_are_unique() -> None:
    keys = [row["field_key"] for row in FIELD_DEFINITION_ROWS]
    assert len(keys) == len(set(keys))


def test_field_types_are_known_values() -> None:
    allowed = {"TEXT", "CHECKLIST", "TABLE"}
    assert {row["field_type"] for row in FIELD_DEFINITION_ROWS} <= allowed


def test_every_field_has_a_description() -> None:
    # description은 app/domain/proposal_llm.py가 LLM 프롬프트에 그대로 넣는 값이라
    # 비어있으면 프롬프트 품질이 떨어진다.
    assert all(row["description"] for row in FIELD_DEFINITION_ROWS)


def test_attachment_checklist_is_checklist_type_not_text() -> None:
    row = next(r for r in FIELD_DEFINITION_ROWS if r["field_key"] == "attachment_checklist")
    assert row["field_type"] == "CHECKLIST"


def test_table_fields_all_have_a_registered_item_schema() -> None:
    # 시딩 데이터(FIELD_DEFINITION_ROWS)와 LLM 스키마 목록(TABLE_ITEM_SCHEMAS)이
    # 서로 다른 파일에 있어 어긋날 수 있다 -- 여기서 교차 확인한다.
    table_field_keys = {row["field_key"] for row in FIELD_DEFINITION_ROWS if row["field_type"] == "TABLE"}
    assert table_field_keys == set(TABLE_ITEM_SCHEMAS.keys())


def test_attachment_checklists_cover_all_template_types() -> None:
    assert set(ATTACHMENT_CHECKLISTS.keys()) == set(TEMPLATE_TYPES)
    assert all(ATTACHMENT_CHECKLISTS[t] for t in TEMPLATE_TYPES)


def test_template_field_map_only_references_known_fields() -> None:
    known_keys = {row["field_key"] for row in FIELD_DEFINITION_ROWS}
    for row in TEMPLATE_FIELD_ROWS:
        assert row["field_key"] in known_keys
        assert row["template_type"] in TEMPLATE_TYPES
        assert row["requirement"] in {"REQUIRED", "OPTIONAL"}


def test_trl_level_is_rnd_required_and_ir_optional_but_not_psst() -> None:
    trl_rows = {
        row["template_type"]: row["requirement"]
        for row in TEMPLATE_FIELD_ROWS
        if row["field_key"] == "trl_level"
    }
    assert trl_rows == {"RND": "REQUIRED", "IR": "OPTIONAL"}


def test_attachment_checklist_required_in_all_three_templates() -> None:
    rows = {row["template_type"] for row in TEMPLATE_FIELD_ROWS if row["field_key"] == "attachment_checklist"}
    assert rows == set(TEMPLATE_TYPES)


# ---------------------------------------------------------------------------
# PDF 검증/추출 헬퍼, 자리표시자 (DB 불필요)
# ---------------------------------------------------------------------------


def test_is_pdf_accepts_pdf_extension_or_content_type() -> None:
    assert _is_pdf(_upload_file("report.pdf", "application/octet-stream"))
    assert _is_pdf(_upload_file("report", "application/pdf"))


def test_is_pdf_rejects_other_files() -> None:
    assert not _is_pdf(_upload_file("report.hwp", "application/x-hwp"))


def test_extract_pdf_text_is_callable() -> None:
    assert callable(_extract_pdf_text)


def test_placeholder_value_is_empty_list_for_table_and_message_for_others() -> None:
    assert _placeholder_value("TABLE", "재무 추정") == []
    text = _placeholder_value("TEXT", "개발 배경·동기")
    assert "개발 배경·동기" in text


# ---------------------------------------------------------------------------
# GET /field-definitions -- template_type 검증은 DB 조회 전이라 마크 불필요
# ---------------------------------------------------------------------------


async def test_get_field_definitions_rejects_unknown_template_type() -> None:
    response = await get_field_definitions("UNKNOWN")
    assert response.status_code == 400
    body = json.loads(response.body)
    assert body["code"] == "PROPOSAL_TEMPLATE_TYPE_INVALID"


@pytest.mark.db
async def test_get_field_definitions_returns_seeded_psst_fields() -> None:
    """scripts/seed_proposal_fields.py 실행 후 로컬 DB로 확인."""
    response = await get_field_definitions("PSST")
    keys = {field.field_key for field in response.result.fields}
    assert "company_overview" in keys
    assert "rd_plan_budget" not in keys  # PSST에서는 제외된 필드


# ---------------------------------------------------------------------------
# app/domain/proposal_llm.py -- 전부 mock, DB/네트워크 불필요
# ---------------------------------------------------------------------------


def test_build_response_schema_maps_text_and_table_fields() -> None:
    schema = build_response_schema(
        [
            {"field_key": "background_motivation", "label": "개발 배경·동기", "field_type": "TEXT"},
            {"field_key": "growth_targets", "label": "정량적 성장목표", "field_type": "TABLE"},
        ]
    )
    props = schema["schema"]["properties"]
    assert props["background_motivation"] == {"type": "string"}
    assert props["growth_targets"]["type"] == "array"
    assert props["growth_targets"]["items"] == TABLE_ITEM_SCHEMAS["growth_targets"]
    assert schema["schema"]["required"] == ["background_motivation", "growth_targets"]


def test_build_response_schema_raises_for_unregistered_table_field() -> None:
    with pytest.raises(ValueError):
        build_response_schema([{"field_key": "does_not_exist", "label": "x", "field_type": "TABLE"}])


def test_proposal_prompt_requires_formal_document_tone() -> None:
    assert "~이다" in _SYSTEM_PROMPT_TEMPLATE
    assert "~한다" in _SYSTEM_PROMPT_TEMPLATE
    assert "~된다" in _SYSTEM_PROMPT_TEMPLATE
    assert "~입니다" in _SYSTEM_PROMPT_TEMPLATE
    assert "~임" in _SYSTEM_PROMPT_TEMPLATE
    assert "~함" in _SYSTEM_PROMPT_TEMPLATE
    assert "~됨" in _SYSTEM_PROMPT_TEMPLATE
    assert "존댓말·대화체" in _SYSTEM_PROMPT_TEMPLATE


async def test_generate_missing_sections_returns_empty_dict_when_no_target_fields() -> None:
    assert await generate_missing_sections("PSST", "report", {}, []) == {}


async def test_generate_missing_sections_raises_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(proposal_llm.settings, "openai_api_key", "")
    with pytest.raises(ProposalLLMUnavailable):
        await generate_missing_sections(
            "PSST", "report text", {}, [{"field_key": "background_motivation", "label": "x", "field_type": "TEXT"}]
        )


async def test_generate_missing_sections_parses_llm_response(monkeypatch) -> None:
    monkeypatch.setattr(proposal_llm.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(proposal_llm.redis_client, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(proposal_llm.redis_client, "set", AsyncMock())

    payload = json.dumps({"background_motivation": "수면 문제는..."})
    with _patched_client(payload) as mock_openai_cls:
        result = await generate_missing_sections(
            "PSST",
            "report text",
            {},
            [{"field_key": "background_motivation", "label": "개발 배경·동기", "field_type": "TEXT"}],
        )
    mock_openai_cls.assert_called_once()
    assert result == {"background_motivation": "수면 문제는..."}


async def test_generate_missing_sections_raises_on_malformed_json(monkeypatch) -> None:
    monkeypatch.setattr(proposal_llm.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(proposal_llm.redis_client, "get", AsyncMock(return_value=None))

    with _patched_client("이건 JSON이 아님"):
        with pytest.raises(ProposalLLMUnavailable):
            await generate_missing_sections(
                "PSST", "report", {}, [{"field_key": "background_motivation", "label": "x", "field_type": "TEXT"}]
            )


async def test_generate_missing_sections_uses_cache_on_second_call(monkeypatch) -> None:
    monkeypatch.setattr(proposal_llm.settings, "openai_api_key", "sk-test")
    store: dict[str, str] = {}

    async def fake_get(key: str):
        return store.get(key)

    async def fake_set(key: str, value: str, ex: int | None = None) -> None:
        store[key] = value

    monkeypatch.setattr(proposal_llm.redis_client, "get", fake_get)
    monkeypatch.setattr(proposal_llm.redis_client, "set", fake_set)

    target_fields = [{"field_key": "background_motivation", "label": "x", "field_type": "TEXT"}]
    payload = json.dumps({"background_motivation": "동일 결과"})

    with _patched_client(payload) as first_call:
        first = await generate_missing_sections("PSST", "report", {}, target_fields)
    first_call.assert_called_once()

    with _patched_client(payload) as second_call:
        second = await generate_missing_sections("PSST", "report", {}, target_fields)
    second_call.assert_not_called()  # 캐시 히트라 OpenAI를 다시 안 부른다.

    assert first == second


# ---------------------------------------------------------------------------
# app/domain/proposal_pdf.py -- 순수 렌더링, DB/네트워크 불필요
# ---------------------------------------------------------------------------


def test_render_proposal_pdf_produces_valid_pdf_bytes() -> None:
    pdf_bytes = render_proposal_pdf(
        "PSST",
        [
            {"field_key": "company_overview", "label": "기업개요·대표자", "field_type": "TEXT", "value": "설명"},
            {"field_key": "attachment_checklist", "label": "첨부서류", "field_type": "CHECKLIST", "value": ["사업자등록증"]},
            {
                "field_key": "growth_targets",
                "label": "정량적 성장목표",
                "field_type": "TABLE",
                "value": [{"year": 1, "revenue_krw": 1000}],
            },
        ],
    )
    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 0


def test_render_proposal_pdf_embeds_korean_font_not_just_referenced() -> None:
    # 회귀 테스트: PDF 표준 CID 폰트(HYGothic-Medium 등)로 처음 구현했을 때 실제로
    # 렌더링해보면 한글 폰트가 없는 뷰어에서 한글이 빈 칸으로 나오는 걸 확인했다
    # (CID 폰트는 폰트 파일 없이 이름만 참조한다). NanumGothic을 /FontFile2로
    # 실제 임베딩해야 어떤 뷰어에서도 항상 동일하게 보인다.
    pdf_bytes = render_proposal_pdf(
        "PSST",
        [{"field_key": "company_overview", "label": "기업개요·대표자", "field_type": "TEXT", "value": "한글 테스트"}],
    )
    assert _font_is_embedded(pdf_bytes, "NanumGothic")


def test_render_proposal_pdf_handles_mismatched_field_type_and_value_without_raising() -> None:
    # 리뷰 중 발견한 회귀: complete 요청의 field_type은 클라이언트가 그대로 보내오므로,
    # 프론트가 실수로 TABLE 필드에 문자열 value를 보내면 고치기 전에는
    # rows[0].keys()에서 AttributeError -> GET /{id}/pdf 전체가 500으로 죽었다.
    pdf_bytes = render_proposal_pdf(
        "PSST",
        [
            {"field_key": "growth_targets", "label": "정량적 성장목표", "field_type": "TABLE", "value": "문자열이 잘못 옴"},
            {"field_key": "attachment_checklist", "label": "첨부서류", "field_type": "CHECKLIST", "value": "이것도 문자열"},
        ],
    )
    assert pdf_bytes[:4] == b"%PDF"


def test_render_proposal_pdf_handles_empty_values_without_raising() -> None:
    pdf_bytes = render_proposal_pdf(
        "IR",
        [
            {"field_key": "esg", "label": "사회적 가치·ESG", "field_type": "TEXT", "value": ""},
            {"field_key": "attachment_checklist", "label": "첨부서류", "field_type": "CHECKLIST", "value": []},
            {"field_key": "cap_table", "label": "지분구조", "field_type": "TABLE", "value": []},
        ],
    )
    assert pdf_bytes[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# complete / pdf -- 실제 Redis 대신 monkeypatch로 대체 (CI에서 실행)
# ---------------------------------------------------------------------------


async def test_complete_proposal_rejects_unknown_template_type() -> None:
    # template_type 검증은 DB 조회 전이라 마크 불필요.
    response = await complete_proposal(
        "prop-1",
        CompleteRequest(template_type="NOPE", sections=[CompleteSection(field_key="company_overview", value="x")]),
    )
    assert response.status_code == 400
    assert json.loads(response.body)["code"] == "PROPOSAL_TEMPLATE_TYPE_INVALID"


@pytest.mark.db
async def test_complete_proposal_stores_payload_with_ttl(monkeypatch) -> None:
    """label/field_type을 서버가 proposal_field_definitions에서 조회하므로 DB 필요."""
    fake_set = AsyncMock()
    monkeypatch.setattr(proposals.redis_client, "set", fake_set)

    request = CompleteRequest(
        template_type="PSST",
        sections=[CompleteSection(field_key="company_overview", value="최종본")],
    )
    response = await complete_proposal("prop-1", request)

    assert response.result.proposal_id == "prop-1"
    fake_set.assert_awaited_once()
    call_args, kwargs = fake_set.call_args
    assert kwargs["ex"] == proposals._PROPOSAL_TTL_SECONDS
    stored = json.loads(call_args[1])
    assert stored["template_type"] == "PSST"
    assert stored["sections"][0]["value"] == "최종본"
    # label/field_type이 요청에 없어도 서버가 채워야 한다.
    assert stored["sections"][0]["label"] == "기업개요·대표자"
    assert stored["sections"][0]["field_type"] == "TEXT"


@pytest.mark.db
async def test_complete_proposal_rejects_unknown_field_key(monkeypatch) -> None:
    monkeypatch.setattr(proposals.redis_client, "set", AsyncMock())
    response = await complete_proposal(
        "prop-1",
        CompleteRequest(
            template_type="PSST", sections=[CompleteSection(field_key="does_not_exist", value="x")]
        ),
    )
    assert response.status_code == 400
    assert json.loads(response.body)["code"] == "PROPOSAL_FIELD_KEY_INVALID"


async def test_get_proposal_pdf_returns_404_when_expired_or_missing(monkeypatch) -> None:
    monkeypatch.setattr(proposals.redis_client, "get", AsyncMock(return_value=None))

    response = await get_proposal_pdf("does-not-exist")
    assert response.status_code == 404
    body = json.loads(response.body)
    assert body["code"] == "PROPOSAL_NOT_FOUND"


async def test_get_proposal_pdf_returns_real_pdf_binary(monkeypatch) -> None:
    cached_payload = json.dumps(
        {
            "proposal_id": "prop-1",
            "template_type": "PSST",
            "sections": [
                {"field_key": "company_overview", "label": "기업개요·대표자", "field_type": "TEXT", "value": "최종본"}
            ],
            "expires_at": "2026-09-07T12:10:00+00:00",
        }
    )
    monkeypatch.setattr(proposals.redis_client, "get", AsyncMock(return_value=cached_payload))

    response = await get_proposal_pdf("prop-1")

    assert response.media_type == "application/pdf"
    assert response.body[:4] == b"%PDF"
    assert "proposal_prop-1.pdf" in response.headers["content-disposition"]


# ---------------------------------------------------------------------------
# app/domain/proposal_sections.py -- custom_fields 병합 (프론트 요청 v6, 2026-09-11)
# ---------------------------------------------------------------------------


def test_merge_custom_fields_returns_sections_unchanged_when_no_custom_fields() -> None:
    sections = [{"field_key": "company_overview", "label": "x", "field_type": "TEXT", "value": "v", "category": "일반현황"}]
    assert merge_custom_fields(sections, []) is sections


def test_merge_custom_fields_inserts_at_end_of_matching_category_block() -> None:
    sections = [
        {"field_key": "company_overview", "label": "기업개요", "field_type": "TEXT", "value": "a", "category": "일반현황"},
        {"field_key": "idea_overview", "label": "아이템개요", "field_type": "TEXT", "value": "b", "category": "일반현황"},
        {"field_key": "background_motivation", "label": "개발배경", "field_type": "TEXT", "value": "c", "category": "문제인식"},
    ]
    custom_fields = [{"category": "일반현황", "label": "추가 항목", "value": "커스텀1"}]

    merged = merge_custom_fields(sections, custom_fields)

    # 일반현황 블록(0,1) 바로 다음, 문제인식(2) 앞에 끼워져야 한다.
    assert [s.get("field_key") for s in merged] == [
        "company_overview", "idea_overview", None, "background_motivation",
    ]
    assert merged[2]["label"] == "추가 항목"
    assert merged[2]["value"] == "커스텀1"
    assert merged[2]["field_type"] == "TEXT"


def test_merge_custom_fields_preserves_order_within_same_category() -> None:
    sections = [{"field_key": "company_overview", "label": "x", "field_type": "TEXT", "value": "a", "category": "일반현황"}]
    custom_fields = [
        {"category": "일반현황", "label": "추가 항목", "value": "첫번째"},
        {"category": "일반현황", "label": "추가 항목", "value": "두번째"},
    ]

    merged = merge_custom_fields(sections, custom_fields)

    assert [s["value"] for s in merged[1:]] == ["첫번째", "두번째"]


def test_merge_custom_fields_appends_unmatched_category_at_the_end() -> None:
    # sections 어디에도 없는 category(오타 등)로 지정되면 자리를 못 찾으므로
    # 문서 끝에 붙는다 -- 값 자체가 사라지는 것보다 안전하다.
    sections = [{"field_key": "company_overview", "label": "x", "field_type": "TEXT", "value": "a", "category": "일반현황"}]
    custom_fields = [{"category": "존재하지않는카테고리", "label": "추가 항목", "value": "고아값"}]

    merged = merge_custom_fields(sections, custom_fields)

    assert merged[-1]["value"] == "고아값"


def test_merge_custom_fields_handles_multiple_categories_independently() -> None:
    sections = [
        {"field_key": "company_overview", "label": "x", "field_type": "TEXT", "value": "a", "category": "일반현황"},
        {"field_key": "founder_capability", "label": "y", "field_type": "TEXT", "value": "b", "category": "팀구성"},
    ]
    custom_fields = [
        {"category": "일반현황", "label": "추가 항목", "value": "일반현황용"},
        {"category": "팀구성", "label": "추가 항목", "value": "팀구성용"},
    ]

    merged = merge_custom_fields(sections, custom_fields)

    assert [s.get("field_key") or s["value"] for s in merged] == [
        "company_overview", "일반현황용", "founder_capability", "팀구성용",
    ]


# ---------------------------------------------------------------------------
# complete_proposal -- category 저장 + custom_fields 전달 (프론트 요청 v6)
# ---------------------------------------------------------------------------


@pytest.mark.db
async def test_complete_proposal_stores_category_and_custom_fields(monkeypatch) -> None:
    fake_set = AsyncMock()
    monkeypatch.setattr(proposals.redis_client, "set", fake_set)

    request = CompleteRequest(
        template_type="PSST",
        sections=[CompleteSection(field_key="company_overview", value="최종본")],
        custom_fields=[CustomField(category="일반현황", label="추가 항목", value="커스텀 값")],
    )
    response = await complete_proposal("prop-1", request)

    assert response.result.proposal_id == "prop-1"
    stored = json.loads(fake_set.call_args[0][1])
    assert stored["sections"][0]["category"] == "일반현황"
    assert stored["custom_fields"] == [{"category": "일반현황", "label": "추가 항목", "value": "커스텀 값"}]


@pytest.mark.db
async def test_complete_proposal_defaults_custom_fields_to_empty_list(monkeypatch) -> None:
    """custom_fields를 아예 안 보내는 기존 클라이언트도 계속 동작해야 한다."""
    fake_set = AsyncMock()
    monkeypatch.setattr(proposals.redis_client, "set", fake_set)

    request = CompleteRequest(
        template_type="PSST", sections=[CompleteSection(field_key="company_overview", value="최종본")]
    )
    await complete_proposal("prop-1", request)

    stored = json.loads(fake_set.call_args[0][1])
    assert stored["custom_fields"] == []


# ---------------------------------------------------------------------------
# app/domain/proposal_docx.py -- 순수 렌더링, DB/네트워크 불필요 (요청 2)
# ---------------------------------------------------------------------------


def _docx_paragraph_texts(docx_bytes: bytes) -> list[str]:
    document = Document(BytesIO(docx_bytes))
    return [p.text for p in document.paragraphs]


def test_render_proposal_docx_produces_valid_docx_bytes() -> None:
    docx_bytes = render_proposal_docx(
        "PSST",
        [
            {"field_key": "company_overview", "label": "기업개요·대표자", "field_type": "TEXT", "value": "설명"},
            {"field_key": "attachment_checklist", "label": "첨부서류", "field_type": "CHECKLIST", "value": ["사업자등록증"]},
            {
                "field_key": "growth_targets",
                "label": "정량적 성장목표",
                "field_type": "TABLE",
                "value": [{"year": 1, "revenue_krw": 1000}],
            },
        ],
    )
    # .docx는 zip 컨테이너다 -- 매직 바이트로 최소한의 형식 확인.
    assert docx_bytes[:2] == b"PK"
    # 실제로 python-docx로 다시 읽어서 내용이 왕복하는지까지 확인한다.
    document = Document(BytesIO(docx_bytes))
    headings = [p.text for p in document.paragraphs if p.style.name.startswith("Heading")]
    assert "기업개요·대표자" in headings
    assert document.tables[0].rows[0].cells[0].text == "year"


def test_render_proposal_docx_handles_mismatched_field_type_and_value_without_raising() -> None:
    # proposal_pdf.py의 동일 테스트와 같은 회귀(field_type/value 불일치)를 docx
    # 렌더러에서도 막는다.
    docx_bytes = render_proposal_docx(
        "PSST",
        [
            {"field_key": "growth_targets", "label": "정량적 성장목표", "field_type": "TABLE", "value": "문자열이 잘못 옴"},
            {"field_key": "attachment_checklist", "label": "첨부서류", "field_type": "CHECKLIST", "value": "이것도 문자열"},
        ],
    )
    assert docx_bytes[:2] == b"PK"
    texts = _docx_paragraph_texts(docx_bytes)
    assert "(형식 오류로 표시할 수 없습니다)" in texts


def test_render_proposal_docx_handles_empty_values_without_raising() -> None:
    docx_bytes = render_proposal_docx(
        "IR",
        [
            {"field_key": "esg", "label": "사회적 가치·ESG", "field_type": "TEXT", "value": ""},
            {"field_key": "attachment_checklist", "label": "첨부서류", "field_type": "CHECKLIST", "value": []},
            {"field_key": "cap_table", "label": "지분구조", "field_type": "TABLE", "value": []},
        ],
    )
    assert docx_bytes[:2] == b"PK"


def test_render_proposal_docx_appended_custom_field_appears_after_its_category() -> None:
    """merge_custom_fields()로 만든 순서를 그대로 렌더링에 넣었을 때, docx
    본문에도 실제로 원래 필드 다음/다음 카테고리 필드 이전에 나오는지 확인한다."""
    sections = merge_custom_fields(
        [
            {"field_key": "company_overview", "label": "기업개요", "field_type": "TEXT", "value": "a", "category": "일반현황"},
            {"field_key": "background_motivation", "label": "개발배경", "field_type": "TEXT", "value": "b", "category": "문제인식"},
        ],
        [{"category": "일반현황", "label": "추가 항목", "value": "커스텀값"}],
    )
    docx_bytes = render_proposal_docx("PSST", sections)
    headings = [p.text for p in Document(BytesIO(docx_bytes)).paragraphs if p.style.name.startswith("Heading")]

    assert headings.index("기업개요") < headings.index("추가 항목") < headings.index("개발배경")


# ---------------------------------------------------------------------------
# GET /{proposal_id}/docx (요청 2)
# ---------------------------------------------------------------------------


async def test_get_proposal_docx_returns_404_when_expired_or_missing(monkeypatch) -> None:
    monkeypatch.setattr(proposals.redis_client, "get", AsyncMock(return_value=None))

    response = await get_proposal_docx("does-not-exist")
    assert response.status_code == 404
    body = json.loads(response.body)
    assert body["code"] == "PROPOSAL_NOT_FOUND"


async def test_get_proposal_docx_returns_real_docx_binary_with_custom_fields(monkeypatch) -> None:
    cached_payload = json.dumps(
        {
            "proposal_id": "prop-1",
            "template_type": "PSST",
            "sections": [
                {
                    "field_key": "company_overview",
                    "label": "기업개요·대표자",
                    "field_type": "TEXT",
                    "value": "최종본",
                    "category": "일반현황",
                }
            ],
            "custom_fields": [{"category": "일반현황", "label": "추가 항목", "value": "커스텀"}],
            "expires_at": "2026-09-07T12:10:00+00:00",
        }
    )
    monkeypatch.setattr(proposals.redis_client, "get", AsyncMock(return_value=cached_payload))

    response = await get_proposal_docx("prop-1")

    assert response.media_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert response.body[:2] == b"PK"
    assert "proposal_prop-1.docx" in response.headers["content-disposition"]
    headings = [p.text for p in Document(BytesIO(response.body)).paragraphs if p.style.name.startswith("Heading")]
    assert "추가 항목" in headings
