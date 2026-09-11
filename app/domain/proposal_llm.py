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

import hashlib
import json

import openai
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.redis_client import redis_client

_REQUEST_TIMEOUT_SECONDS = 30.0  # 여러 필드를 한 번에 생성하므로 correction_llm.py(15초)보다 여유를 둠
_CACHE_TTL_SECONDS = 600  # 완료(§0) 전 재생성 재시도 비용 절감용 -- 제안서 자체의 10분 TTL과는 별개 목적
# 프롬프트가 바뀌면 이전 프롬프트로 만든 캐시를 그대로 반환하지 않도록 버전을 올린다.
# v4(2026-09-11): 대표자 경력 등 리포트에 없는 사실을 그럴듯하게 지어내는 할루시네이션이
# 실사용 중 발견되어(사용자 리포트) 사실 근거 원칙을 강화하며 버전 갱신.
_CACHE_KEY_PREFIX = "proposal_generation:v4:"

# 리포트/사용자 입력 둘 다에 근거가 없을 때 TEXT 필드가 반환해야 하는 고정 문구.
# 정확히 이 문자열인지 코드에서도 확인할 수 있게 상수로 뽑아둔다.
NO_GROUNDING_PLACEHOLDER = "[검진 리포트에 근거 정보가 없습니다. 직접 작성해주세요.]"

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

각 필드를 쓰기 전에 스스로 먼저 확인하세요: "[검진 리포트]나 [사용자가 이미 입력한
내용]에 이 필드와 관련된 내용이 실제로 적혀 있는가?"

**없다면**, 절대 채우지 마세요. 두루뭉술하고 그럴듯하게 들리는 문장("전문성을 보유하고
있다", "관련 경험이 있다", "역량을 갖추고 있다" 같은 것)도 근거 없는 사실 창작이며
엄격히 금지됩니다. 이 경우 TEXT 필드는 정확히 아래 문자열만 반환하세요(한 글자도
바꾸지 마세요), TABLE 필드는 빈 배열 []을 반환하세요:
"{no_grounding_placeholder}"

**예시** -- 리포트에 서비스 설명·시장성·카테고리만 있고 대표자에 대한 언급이 전혀 없는
경우: founder_capability는 위 placeholder 문자열 그대로 반환해야 합니다. "IT 분야
경험이 있다", "전문성을 갖췄다" 같은 문장을 쓰면 안 됩니다 -- 리포트가 대표자에 대해
아무것도 말해주지 않기 때문입니다.

특히 아래는 리포트에 없으면 반드시 placeholder로 남기세요:
- 대표자·팀원의 구체적 경력, 학력, 근무 연차, 이전 소속 회사, 자격증, 수상 이력
- 존재하지 않는 기관명·회사명·인물명·통계 수치·설문 결과
- 회사의 구체적 연혁, 매출 실적, 계약·수주 실적
- founder_capability, team_hiring_plan, rd_track_record, bonus_criteria는 리포트에
  근거가 없는 경우가 대부분이니 기본값을 "채운다"가 아니라 "placeholder"로 두세요.

**예외** -- growth_targets, annual_budget_exec, financial_projection은 성격상
향후 계획·추정치를 요구하는 필드입니다. 리포트의 시장 규모·카테고리 등 간접 정보를
근거로 사용자가 검토할 초안 추정치를 제시하세요(이 필드에는 placeholder를 쓰지
마세요). 존재하지 않는 구체 기관명·통계는 인용하지 말고, 추정 근거를 basis에 명시해
추정치임을 분명히 하세요.

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


def build_response_schema(target_fields: list[dict]) -> dict:
    """target_fields: [{"field_key", "label", "field_type", ...}, ...] (CHECKLIST 제외).

    TABLE 필드는 TABLE_ITEM_SCHEMAS에 항목 스키마가 등록돼 있어야 한다 -- 없으면
    시딩 데이터와 이 모듈의 스키마 목록이 어긋난 것이므로 조용히 넘기지 않고 바로 에러.
    """
    properties: dict = {}
    for field in target_fields:
        if field["field_type"] == "TABLE":
            item_schema = TABLE_ITEM_SCHEMAS.get(field["field_key"])
            if item_schema is None:
                raise ValueError(f"TABLE_ITEM_SCHEMAS에 {field['field_key']} 항목 스키마가 없습니다.")
            properties[field["field_key"]] = {"type": "array", "items": item_schema}
        else:
            properties[field["field_key"]] = {"type": "string"}

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


async def generate_missing_sections(
    template_type: str,
    report_text: str,
    field_values: dict,
    target_fields: list[dict],
) -> dict[str, object]:
    """target_fields가 비어있으면(전부 사용자가 채웠거나 CHECKLIST뿐이면) 빈 dict를 반환한다.

    반환값은 {field_key: str}(TEXT) 또는 {field_key: [dict, ...]}(TABLE)이 섞여 있다.
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

    client = _build_client()
    schema = build_response_schema(target_fields)
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
        template_label=_TEMPLATE_LABELS.get(template_type, template_type),
        no_grounding_placeholder=NO_GROUNDING_PLACEHOLDER,
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
        sections = json.loads(response.choices[0].message.content)
    except openai.OpenAIError as error:
        raise ProposalLLMUnavailable(f"OpenAI 호출 실패: {error}") from error
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise ProposalLLMUnavailable(f"OpenAI 응답 형식이 예상과 다릅니다: {error}") from error

    try:
        await redis_client.set(cache_key, json.dumps(sections, ensure_ascii=False), ex=_CACHE_TTL_SECONDS)
    except Exception:
        pass  # 캐시 저장 실패도 치명적이지 않다.

    return sections
