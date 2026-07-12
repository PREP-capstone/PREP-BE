"""[4]+[5] Stage A 프롬프트 주입 + LLM 호출 노드.

참고: docs/langgraph_파이프라인_설계서.md §4 (extract_A)
출력 스키마: docs/db_구축_설계서.md §4.2 Stage A — gate_keywords
{
  "type": "DISEASE | PROHIBITED_ACTION | DOCTOR_REPLACEMENT",
  "keyword": "",
  "keyword_category": "DIAGNOSIS | TREATMENT | DATA_TYPE | OTHER",
  "data_type_focus": "IMAGING | NUMERIC | TEXT | LIFESTYLE | NONE",
  "verdict": "FAIL_CANDIDATE | CONTEXT_CHECK | FAIL_CONFIRMED",
  "weight": 0,
  "legal_basis": {"document_id": "", "article": "", "quote": ""}
}

legal_basis.document_id는 LLM에게 묻지 않고 현재 문서의 document_id를 코드에서 채운다
(LLM이 문서 id를 지어낼 위험을 없애기 위함). article/quote만 LLM 출력 대상.
한 청크에서 0개 이상의 키워드 후보가 나올 수 있으므로 응답을 "keywords" 배열로 감싼다.
"""

import json

from openai import AsyncOpenAI

from app.core.config import settings
from app.pipeline.state import ExtractedDraft, PipelineState

_RESPONSE_SCHEMA = {
    "name": "gate_a_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "keywords": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["DISEASE", "PROHIBITED_ACTION", "DOCTOR_REPLACEMENT"],
                        },
                        "keyword": {"type": "string"},
                        "keyword_category": {
                            "type": "string",
                            "enum": ["DIAGNOSIS", "TREATMENT", "DATA_TYPE", "OTHER"],
                        },
                        "data_type_focus": {
                            "type": "string",
                            "enum": ["IMAGING", "NUMERIC", "TEXT", "LIFESTYLE", "NONE"],
                        },
                        "verdict": {
                            "type": "string",
                            "enum": ["FAIL_CANDIDATE", "CONTEXT_CHECK", "FAIL_CONFIRMED"],
                        },
                        "weight": {"type": "integer"},
                        "legal_basis": {
                            "type": "object",
                            "properties": {
                                "article": {"type": "string"},
                                "quote": {"type": "string"},
                            },
                            "required": ["article", "quote"],
                            "additionalProperties": False,
                        },
                    },
                    "required": [
                        "type",
                        "keyword",
                        "keyword_category",
                        "data_type_focus",
                        "verdict",
                        "weight",
                        "legal_basis",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["keywords"],
        "additionalProperties": False,
    },
}

_SYSTEM_PROMPT = """당신은 의료기기 판단 가이드/법령 조문에서 gate_keywords 후보를 추출하는 전문가입니다.
주어진 조문 텍스트를 읽고, 의료기기 해당 여부 판단에 쓰일 키워드 후보를 0개 이상 추출하세요.
관련 키워드가 없으면 keywords를 빈 배열로 반환하세요.

## weight 척도 (1~5, 정수만)
- 5: 고위해도 직접 해당 + 의료행위 명시 (지침서-0091-03 Ⅲ.2.가·나 고위해도 5요소: 생체적합성 문제/침습적/오작동 시 상해/위급상황 탐지/기기 통제·변경)
- 4: 의료 목적 강하게 암시, 단독 FAIL 후보 (의료기기법 제2조제1항: 질병의 진단·치료·경감·처치·예방, 상해·장애 보정)
- 3: 의료 맥락이면 위험, 웰니스 맥락이면 허용 가능 (지침서-0091-03 Ⅳ.2.가 만성질환 현상 관리용 경계)
- 2: 경계선 키워드, 웰니스 가능성 있음 (지침서-0091-03 Ⅲ.2.다 저위해도: 질병 언급 없는 측정·모니터링)
- 1: 웰니스 키워드, 참고용 (지침서-0091-03 Ⅲ.가 + Ⅳ.1 일상건강관리용)

## verdict = FAIL_CONFIRMED로 직접 지정하는 조건 (하나라도 해당하면)
1. 고위해도 5가지 중 하나라도 해당 (Ⅲ.2.가·나)
2. 의료기기 정의 4가지 목적 명시 (진단/치료/경감/처치/예방/상해 보정/구조·기능 변형)
3. type = DOCTOR_REPLACEMENT (의사 진단·처방 대체는 무조건 의료행위)
4. weight = 5 AND type = DISEASE

## 신호어
- FAIL 방향: "해당한다", "의료기기로 본다", "제외한다", "고위해도", "아님"
- PASS 방향: "해당하지 않는다", "저위해도", "개인용건강관리제품"
- CONDITIONAL 방향: "단,", "다만,", "경우에 한하여"

## legal_basis
- article: 이 키워드 판단의 근거가 되는 조문 번호/제목 (예: "Ⅲ.2.가", "제24조")
- quote: 판단 근거가 되는 원문 문장을 그대로 인용 (반드시 아래 조문 텍스트 안에 실제로 존재하는 문장이어야 함. 지어내지 말 것)
"""


def _build_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key)


async def extract_A(state: PipelineState) -> dict:
    client = _build_client()
    drafts: list[ExtractedDraft] = list(state["drafts"])

    for chunk in state["chunks"]:
        if not chunk["content"].strip():
            continue

        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": chunk["content"]},
            ],
            response_format={"type": "json_schema", "json_schema": _RESPONSE_SCHEMA},
        )
        parsed = json.loads(response.choices[0].message.content)

        for item in parsed["keywords"]:
            legal_basis = {
                "document_id": state["document_id"],
                "article": item["legal_basis"]["article"],
                "quote": item["legal_basis"]["quote"],
            }
            fields = {**item, "legal_basis": legal_basis}
            drafts.append({"stage": "A", "fields": fields, "legal_basis": legal_basis})

    return {"drafts": drafts}
