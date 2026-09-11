"""제안서 자동 작성 LLM 생성 (이슈 #102, docs/제안서_자동작성_API_명세서.md).

app/domain/correction_llm.py와 동일한 컨벤션(AsyncOpenAI, temperature=0 고정 출력,
json_schema strict 모드, Redis 캐싱, XxxUnavailable 예외)을 따른다.

**필드 하나당 호출 하나가 아니라, 유형(template_type) 하나당 호출 하나로 묶는다** --
app/pipeline/nodes/extract_b.py가 "LLM은 표에서 조회만" 원칙으로 호출 수를 줄이는 것과
같은 이유로, 33개 필드를 각각 부르면 비용/지연이 33배가 된다. 사용자가 이미 값을 채운
필드와 CHECKLIST 타입 필드(attachment_checklist -- 유형별 고정 목록, LLM 미사용)는
애초에 target_fields로 넘어오지 않는다(app/api/proposals.py가 걸러서 넘김).

§10.1 원칙("LLM 장애로 핵심 응답이 깨지면 안 된다")에 따라, 이 모듈이 실패해도
app/api/proposals.py는 요청 전체를 502로 죽이지 않고 자리표시자로 대체한다. 다만
report_llm.py의 보조 필드(LLM④⑤)와 달리 여기는 생성 결과 자체가 핵심 응답이므로,
실패를 조용히 숨기지 않고 GenerateResult.llm_status로 프론트에 알린다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

import openai
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.redis_client import redis_client

_REQUEST_TIMEOUT_SECONDS = 30.0  # 여러 필드를 한 번에 생성하므로 correction_llm.py(15초)보다 여유를 둠
_CACHE_TTL_SECONDS = 600  # 완료(§0) 전 재생성 재시도 비용 절감용 -- 제안서 자체의 10분 TTL과는 별개 목적
# 프롬프트/응답 스키마가 바뀌면 이전 버전으로 만든 캐시를 그대로 반환하지 않도록
# 버전을 올린다.
# v4(2026-09-11): 대표자 경력 등 할루시네이션 발견, 프롬프트 문구만 강화 -- 그러나
# founder_capability(예시로 든 필드)만 지켜지고 team_hiring_plan/company_overview
# 등 다른 필드는 여전히 지어내는 것을 20필드 배치 실측으로 확인, 프롬프트만으론 불충분.
# v5(2026-09-11): TEXT 필드 응답 스키마 자체를 {has_report_basis, content}로 바꿔
# 근거 없음 판단을 모델의 산문 성향이 아니라 코드(_normalize_sections)가 강제하도록
# 구조 변경.
_CACHE_KEY_PREFIX = "proposal_generation:v5:"

# 리포트/사용자 입력 둘 다에 근거가 없을 때 TEXT 필드가 반환해야 하는 고정 문구.
# 정확히 이 문자열인지 코드에서도 확인할 수 있게 상수로 뽑아둔다.
NO_GROUNDING_PLACEHOLDER = "[검진 리포트에 근거 정보가 없습니다. 직접 작성해주세요.]"

# 대표자/팀/실적처럼 검진 리포트에 원래 근거가 거의 없는 필드들 -- generate_missing_sections()가
# 이 필드들을 나머지 필드와 분리해 별도 호출로 묻는다(실측, 2026-09-11: 20개 필드를 한
# 호출에 몰아넣으면 이 필드들의 has_report_basis 자기점검이 종종 무너짐).
HALLUCINATION_PRONE_FIELDS: frozenset[str] = frozenset(
    {"founder_capability", "team_hiring_plan", "rd_track_record", "bonus_criteria"}
)

# TABLE 필드별 항목 스키마 -- docs/제안서_자동작성_API_명세서.md §2의 표 구조를 그대로 반영.
# 새 TABLE 필드가 추가되면 여기에도 항목 스키마를 등록해야 한다(build_response_schema가 조회).
TABLE_ITEM_SCHEMAS: dict[str, dict] = {
    "growth_targets": {
        "type": "object",
        "properties": {
            "year": {"type": "integer", "description": "사업 시작 후 n년차(1~3)"},
            "revenue_krw": {"type": "integer", "description": "해당 연도 매출 목표(원)"},
            "headcount": {"type": "integer", "description": "해당 연도 고용 목표(명)"},
            "basis": {"type": "string", "description": "추정 근거 한 줄"},
        },
        "required": ["year", "revenue_krw", "headcount", "basis"],
        "additionalProperties": False,
    },
    "annual_budget_exec": {
        "type": "object",
        "properties": {
            "year": {"type": "integer"},
            "government_fund_krw": {"type": "integer", "description": "정부출연금(원)"},
            "self_fund_cash_krw": {"type": "integer", "description": "자기부담금 현금(원)"},
            "self_fund_in_kind_krw": {"type": "integer", "description": "자기부담금 현물(원)"},
        },
        "required": ["year", "government_fund_krw", "self_fund_cash_krw", "self_fund_in_kind_krw"],
        "additionalProperties": False,
    },
    "financial_projection": {
        "type": "object",
        "properties": {
            "year": {"type": "integer"},
            "revenue_krw": {"type": "integer"},
            "cost_krw": {"type": "integer"},
            "operating_profit_krw": {"type": "integer"},
        },
        "required": ["year", "revenue_krw", "cost_krw", "operating_profit_krw"],
        "additionalProperties": False,
    },
    "cap_table": {
        "type": "object",
        "properties": {
            "shareholder": {"type": "string", "description": "주주 구분(대표자/공동창업자/투자자 등)"},
            "equity_percent": {"type": "number", "description": "지분율(%)"},
        },
        "required": ["shareholder", "equity_percent"],
        "additionalProperties": False,
    },
}

# attachment_checklist(CHECKLIST 타입)는 LLM을 쓰지 않는다 -- 유형별 고정 서류 목록.
# ⚠️ 실제 공고문마다 요구 서류가 조금씩 다르다. 통상적으로 공통 요구되는 항목 기준의
# 초안이며, 배포 전 실제 공고문으로 재대조가 필요하다(이슈 #102 §6 후속 논의로 등록).
ATTACHMENT_CHECKLISTS: dict[str, list[str]] = {
    "PSST": ["사업자등록증(또는 사업자등록 예정 확인서)", "대표자 신분증 사본", "개인정보 수집·이용 동의서"],
    "RND": ["사업자등록증", "연구책임자 이력서", "참여연구원 확인서", "최근 결산 재무제표"],
    "IR": ["사업자등록증", "최근 결산 재무제표", "정관", "주주명부(캡테이블)"],
}

_TEMPLATE_LABELS = {
    "PSST": "창업사업화 지원사업 (PSST 표준형)",
    "RND": "R&D 과제형 (기술개발사업)",
    "IR": "투자유치용 (IR)",
}

_SYSTEM_PROMPT_TEMPLATE = """당신은 대한민국 정부 창업지원사업 사업계획서 작성을 돕는
전문 컨설턴트입니다. 지금 작성하는 문서는 "{template_label}" 유형입니다.

## 사실 근거 원칙 (다른 모든 규칙보다 우선합니다 -- 위반하면 사용자가 지원사업 심사에서
허위 기재로 불이익을 받을 수 있는, 실제로 발생한 사고입니다)

일반 문단(TEXT) 필드는 `has_report_basis`(불리언)와 `content`(문자열) 두 값을 함께
요구받습니다. **모든 TEXT 필드 각각에 대해 예외 없이** 아래 질문에 먼저 스스로
답하세요 -- 필드 이름이 무엇이든 똑같이 적용합니다:

"[검진 리포트]나 [사용자가 이미 입력한 내용]에 이 필드와 직접 관련된 구체적인 내용이
실제로 적혀 있는가?"

- 있다면: `has_report_basis: true`, `content`에 그 근거를 활용해 작성합니다.
- **없다면**: `has_report_basis: false`로 답하고 `content`는 빈 문자열로 둡니다.
  `has_report_basis: true`로 답해놓고 두루뭉술하고 그럴듯하게 들리는 문장("전문성을
  보유하고 있다", "역량을 갖추고 있다", "경험이 있다" 같은 것)으로 content를 채우는
  것은 근거 없는 사실 창작이며 엄격히 금지됩니다 -- 근거가 없으면 반드시 false입니다.

**예시** (리포트에 서비스 설명·시장성·카테고리만 있고 대표자·팀에 대한 언급이 전혀
없는 경우):
- founder_capability -> has_report_basis: false (대표자 개인 경력은 리포트에 없음)
- team_hiring_plan -> has_report_basis: false (팀 구성 정보가 리포트에 없음)
- company_overview -> has_report_basis: true로 서비스 설명 부분은 쓰되, 그 안에
  대표자 경력처럼 리포트에 없는 내용을 끼워넣지 않습니다.

TABLE 필드(growth_targets, annual_budget_exec, financial_projection 등)는
`has_report_basis`가 없습니다 -- 이런 필드는 성격상 향후 계획·추정치를 요구하므로
리포트의 시장 규모·카테고리 등 간접 정보를 근거로 사용자가 검토할 초안 추정치를
항상 제시하세요. 다만 존재하지 않는 구체 기관명·통계를 인용하지 말고, 추정 근거를
basis에 명시해 추정치임을 분명히 하세요.

## 그 외 규칙
- 사업계획서 심사위원이 읽는 공식 문서체로, 과장 없이 정량적 근거를 포함해 작성합니다.
- 문장 종결은 제안서·사업계획서 문체로 통일합니다. 기본적으로 "~이다", "~한다", "~된다"와
  같은 완전한 서술문을 사용합니다.
- "~입니다", "~합니다", "~하세요"와 같은 존댓말·대화체와 "~임", "~함", "~됨"과 같은
  축약형·메모식 종결은 사용하지 않습니다.
- 표와 목록도 가능한 경우 완전한 서술문으로 작성하고, 문서 전체에서 종결 어미를 일관되게
  유지합니다.
- "치료", "진단", "처방" 등 의료행위로 오인될 수 있는 표현은 쓰지 않습니다 -- PREP
  GATE 판정 기준과 상충하면 이 서비스의 지원 자격 자체가 위험해집니다.
- 요청받은 필드만 채우세요. 요청하지 않은 필드는 만들지 마세요.
"""


class ProposalLLMUnavailable(Exception):
    """OPENAI_API_KEY 미설정 또는 호출 실패(레이트리밋·타임아웃·malformed 응답 포함) 시."""


def _build_client() -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise ProposalLLMUnavailable("OPENAI_API_KEY가 설정되지 않았습니다.")
    return AsyncOpenAI(api_key=settings.openai_api_key, timeout=_REQUEST_TIMEOUT_SECONDS)


# TEXT 필드 하나를 표현하는 하위 스키마 -- 리포트/사용자 입력에 근거가 있는지를 모델이
# has_report_basis로 먼저 명시적으로 답하게 강제한다. "그냥 문자열 하나 써라"보다 이렇게
# 판단을 별도 필드로 분리해두면 실제로 훨씬 안정적이다 -- 실측(2026-09-11): 프롬프트
# 문구만으로는 20개 필드를 한 번에 생성할 때 founder_capability(예시로 직접 지목한
# 필드)만 지켜지고 team_hiring_plan/company_overview 등 다른 필드는 여전히 대표자 경력
# 등을 지어냈다. has_report_basis가 false인데도 content에 그럴듯한 글을 쓸 수는 있지만,
# 최종적으로 사용하는 값은 코드가 has_report_basis를 보고 결정하므로(_normalize_sections)
# 모델의 산문 생성 성향과 무관하게 결과가 강제된다.
_TEXT_FIELD_SCHEMA = {
    "type": "object",
    "properties": {
        "has_report_basis": {
            "type": "boolean",
            "description": (
                "[검진 리포트]나 [사용자가 이미 입력한 내용]에 이 필드와 관련된 내용이 "
                "실제로 적혀 있으면 true, 전혀 없으면 false. 이 필드가 growth_targets 같은 "
                "추정치 필드가 아닌 이상, 정확한 사실을 모르면 false로 답하세요."
            ),
        },
        "content": {
            "type": "string",
            "description": (
                "has_report_basis가 true일 때만 실제 작성 내용을 채우세요. "
                "false라면 이 필드는 어차피 쓰이지 않으니 빈 문자열로 두세요."
            ),
        },
    },
    "required": ["has_report_basis", "content"],
    "additionalProperties": False,
}

# growth_targets 등 "예외" 필드(추정치가 정상 업무인 필드)는 has_report_basis 판단 없이
# 항상 채운다 -- TABLE은 이미 그렇고, TEXT 중에서도 있다면 여기 추가한다.
_ALWAYS_FILL_TEXT_FIELDS: frozenset[str] = frozenset()


def build_response_schema(target_fields: list[dict]) -> dict:
    """target_fields: [{"field_key", "label", "field_type", ...}, ...] (CHECKLIST 제외).

    TABLE 필드는 TABLE_ITEM_SCHEMAS에 항목 스키마가 등록돼 있어야 한다 -- 없으면
    시딩 데이터와 이 모듈의 스키마 목록이 어긋난 것이므로 조용히 넘기지 않고 바로 에러.
    TEXT 필드는 _TEXT_FIELD_SCHEMA(has_report_basis + content)를 쓴다 -- 반환값을
    그대로 API에 내보내지 않고 generate_missing_sections()의 _normalize_sections()가
    한 번 더 가공한다.
    """
    properties: dict = {}
    for field in target_fields:
        if field["field_type"] == "TABLE":
            item_schema = TABLE_ITEM_SCHEMAS.get(field["field_key"])
            if item_schema is None:
                raise ValueError(f"TABLE_ITEM_SCHEMAS에 {field['field_key']} 항목 스키마가 없습니다.")
            properties[field["field_key"]] = {"type": "array", "items": item_schema}
        elif field["field_key"] in _ALWAYS_FILL_TEXT_FIELDS:
            properties[field["field_key"]] = {"type": "string"}
        else:
            properties[field["field_key"]] = _TEXT_FIELD_SCHEMA

    return {
        "name": "proposal_sections",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": properties,
            "required": [field["field_key"] for field in target_fields],
            "additionalProperties": False,
        },
    }


def _normalize_sections(raw_sections: dict, target_fields: list[dict]) -> dict[str, object]:
    """build_response_schema()가 만든 스키마의 원시 응답을 API가 쓰는 최종 형태로 가공한다.

    TABLE과 _ALWAYS_FILL_TEXT_FIELDS는 그대로 통과. 그 외 TEXT 필드는
    {"has_report_basis", "content"} 객체를 받아 has_report_basis가 false면 값을
    NO_GROUNDING_PLACEHOLDER로 강제 교체한다 -- 모델이 content에 뭘 썼든 무시한다.
    """
    field_types = {field["field_key"]: field["field_type"] for field in target_fields}
    normalized: dict[str, object] = {}
    for key, value in raw_sections.items():
        field_type = field_types.get(key)
        if field_type == "TABLE" or key in _ALWAYS_FILL_TEXT_FIELDS:
            normalized[key] = value
        elif isinstance(value, dict):
            normalized[key] = value.get("content", "") if value.get("has_report_basis") else NO_GROUNDING_PLACEHOLDER
        else:
            # strict json_schema가 보장하니 정상 상황에선 여기 안 온다 -- 방어적으로만 통과.
            normalized[key] = value
    return normalized


def _build_user_prompt(report_text: str, field_values: dict, target_fields: list[dict]) -> str:
    guide_lines = "\n".join(
        f"- {field['field_key']} ({field['label']}): {field.get('description') or '작성 가이드 없음'}"
        for field in target_fields
    )
    filled_lines = (
        "\n".join(
            f"- {key}: {value}"
            for key, value in field_values.items()
            if isinstance(value, str) and value.strip()
        )
        or "(없음)"
    )

    return f"""[작성해야 할 항목]
{guide_lines}

[검진 리포트]
{report_text[:6000]}

[사용자가 이미 입력한 내용 -- 참고용, 모순되지 않게 작성]
{filled_lines}

위 항목들을 각각 작성해 요청된 JSON 형식으로만 응답하세요."""


def _cache_key(template_type: str, report_text: str, field_values: dict, target_fields: list[dict]) -> str:
    # report_text는 프롬프트에 넣기 전 6000자로 자르므로(_build_user_prompt), 캐시 키도
    # 똑같이 잘라서 해시한다 -- 안 그러면 6000자 이후만 다른 리포트가 매번 캐시 미스로
    # 새로 호출돼 캐싱 효과가 없어진다.
    payload = json.dumps(
        {
            "template_type": template_type,
            "report_text": report_text[:6000],
            "field_values": field_values,
            "target_field_keys": sorted(field["field_key"] for field in target_fields),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return _CACHE_KEY_PREFIX + hashlib.sha256(payload.encode()).hexdigest()


async def _call_llm_batch(
    template_type: str,
    report_text: str,
    field_values: dict,
    target_fields: list[dict],
) -> dict[str, object]:
    """target_fields 하나의 배치에 대해 실제 OpenAI 호출 1번을 수행하고 정규화까지 마친다."""
    client = _build_client()
    schema = build_response_schema(target_fields)
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        template_label=_TEMPLATE_LABELS.get(template_type, template_type)
    )
    user_prompt = _build_user_prompt(report_text, field_values, target_fields)

    try:
        async with client:
            response = await client.chat.completions.create(
                model=settings.openai_model,
                temperature=0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_schema", "json_schema": schema},
            )
        raw_sections = json.loads(response.choices[0].message.content)
    except openai.OpenAIError as error:
        raise ProposalLLMUnavailable(f"OpenAI 호출 실패: {error}") from error
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise ProposalLLMUnavailable(f"OpenAI 응답 형식이 예상과 다릅니다: {error}") from error

    try:
        return _normalize_sections(raw_sections, target_fields)
    except (KeyError, TypeError, AttributeError) as error:
        raise ProposalLLMUnavailable(f"OpenAI 응답 형식이 예상과 다릅니다: {error}") from error


async def generate_missing_sections(
    template_type: str,
    report_text: str,
    field_values: dict,
    target_fields: list[dict],
) -> dict[str, object]:
    """target_fields가 비어있으면(전부 사용자가 채웠거나 CHECKLIST뿐이면) 빈 dict를 반환한다.

    반환값은 {field_key: str}(TEXT) 또는 {field_key: [dict, ...]}(TABLE)이 섞여 있다.

    ⚠️ HALLUCINATION_PRONE_FIELDS는 나머지 필드와 **별도 호출**로 분리한다(실측,
    2026-09-11): founder_capability/team_hiring_plan을 다른 16~17개 필드와 한
    호출에 몰아넣으면 has_report_basis 자기점검이 종종 무너져 근거 없이 content를
    채우는 것을 확인했다. 같은 필드들만 작은 배치로 따로 물으면 훨씬 안정적이다.
    "유형당 호출 1번" 원칙은 유지하되(§docstring 상단), 이 경우만 최대 2번까지 허용한다.
    """
    if not target_fields:
        return {}

    cache_key = _cache_key(template_type, report_text, field_values, target_fields)
    try:
        cached = await redis_client.get(cache_key)
        if cached is not None:
            return json.loads(cached)
    except Exception:
        pass  # 캐시 조회 실패는 치명적이지 않다 -- 그냥 다시 계산한다.

    prone_fields = [f for f in target_fields if f["field_key"] in HALLUCINATION_PRONE_FIELDS]
    normal_fields = [f for f in target_fields if f["field_key"] not in HALLUCINATION_PRONE_FIELDS]
    batches = [batch for batch in (normal_fields, prone_fields) if batch]

    results = await asyncio.gather(
        *(_call_llm_batch(template_type, report_text, field_values, batch) for batch in batches)
    )
    sections: dict[str, object] = {}
    for result in results:
        sections.update(result)

    try:
        await redis_client.set(cache_key, json.dumps(sections, ensure_ascii=False), ex=_CACHE_TTL_SECONDS)
    except Exception:
        pass  # 캐시 저장 실패도 치명적이지 않다.

    return sections
