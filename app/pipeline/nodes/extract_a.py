"""[4]+[5] Stage A 프롬프트 주입 + LLM 호출 노드. gate_keywords 스키마로 구조화 출력을 받는다.
legal_basis.document_id는 LLM 대신 코드에서 채우고, 청크당 0개 이상의 keywords 배열로 응답받는다.
"""

import json

from openai import AsyncOpenAI

from app.core.config import settings
from app.pipeline.article_ref import (
    ARTICLE_NOTATION_PROMPT,
    build_chunk_message,
    normalize_article,
)
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

## type 분류 기준 (db_구축_설계서.md §3.2)
키워드가 **무엇인지**에 따라 고르세요. 아래 셋 중 하나입니다.
| type | 정의 | 예시 키워드 |
|---|---|---|
| DISEASE | 질병명·생체지표 등 **명사**가 그대로 키워드인 경우 | "당뇨", "부정맥", "혈당", "혈압", "심전도" |
| PROHIBITED_ACTION | 면허 없이 하면 안 되는 **행위**를 가리키는 경우 | "진단", "처방", "조제", "치료법 제공" |
| DOCTOR_REPLACEMENT | 의사의 진단·처방을 **대체한다**고 명시한 경우 | "전문의 없이", "의사 상담 없이 처방" |

⚠️ 셋 중 PROHIBITED_ACTION만 반복해서 쓰지 마세요. 조문에서 뽑히는 키워드는 대부분
질병명·생체지표(DISEASE)이거나 판단 대상 데이터입니다. 행위를 가리키는 키워드일 때만
PROHIBITED_ACTION을 고르고, 의사 대체를 명시한 경우에만 DOCTOR_REPLACEMENT를 고르세요.

## keyword_category 분류 기준
| keyword_category | 정의 | 의료기기법 제2조 대응 목적 | 예시 키워드 |
|---|---|---|---|
| DIAGNOSIS | 질병의 유무·정도를 판별하는 단계 | "질병의 진단" | "혈당 진단", "암 검사", "부정맥 진단", "질환 여부 판별" |
| TREATMENT | 처치·개선·예방을 지시·유도하는 단계 (치료·경감·처치·예방·상해 및 장애의 보정을 하나로 포괄) | "치료·경감·처치·예방", "상해·장애의 보정" | "약물추천", "처치안내", "증상 완화 유도", "재활 보정 안내" |
| DATA_TYPE | 특정 생체지표·병명 자체가 키워드로 쓰이는 경우 | — | "혈당", "혈압", "심전도", "당뇨" |
| OTHER | 위 세 가지에 해당하지 않는 경우 | — | — |

TREATMENT는 의료기기법 제2조가 나열한 치료·경감·처치·예방·상해 및 장애의 보정 5가지 목적을 하나로 묶은 범주입니다.

### 좁은 예외 — 약무행위 (약사법 근거)
**아래 4개 낱말이 실제로 등장할 때만** 적용하는 예외입니다: `처방` · `조제` · `복약지도` · `투약`
(예: "맞춤형 영양제 처방"). 이 경우에만 `type=PROHIBITED_ACTION`, `keyword_category=TREATMENT`로
분류하세요. 약무행위는 별도 축을 만들지 않고 regulatory_score에 흡수하기로 확정돼, 여기서
잡히지 않으면 0점으로 통과하기 때문입니다.

⚠️ 이 예외를 넓게 적용하지 마세요. "자가 측정", "진단·치료", "모니터링"처럼 약을 다루지 않는
표현은 약무행위가 **아닙니다** — 위의 일반 type/keyword_category 기준으로 판단하세요.

DIAGNOSIS와 TREATMENT 사이에 weight 차등은 없습니다 — keyword_category는 weight/verdict 판정과 무관하게 관리자 검수 편의를 위한 분류일 뿐이며, 둘 다 아래 weight 척도·FAIL_CONFIRMED 기준을 동일하게 따릅니다.

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
- article: 이 키워드 판단의 근거가 되는 조문 번호/제목 (예: "III.2.가", "제24조")
- quote: 판단 근거가 되는 원문 문장을 그대로 인용 (반드시 아래 조문 텍스트 안에 실제로 존재하는 문장이어야 함. 지어내지 말 것)

""" + ARTICLE_NOTATION_PROMPT


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
            # 룰베이스 구축은 재현 가능해야 한다. 같은 조문을 다시 돌렸을 때 다른 룰이 나오면
            # 검수·회귀 판단의 근거가 사라지므로 온도를 0으로 고정한다.
            # 참고: temperature=0으로도 원본 출력은 완전히 재현되지 않는다(모델이 비트 단위로
            # 결정적이지 않음). seed 고정도 시도했으나 효과가 없어 되돌렸다 — 재현성은
            # 검증·중복판정 단계가 흡수한다.
            temperature=0,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": build_chunk_message(chunk)},
            ],
            response_format={"type": "json_schema", "json_schema": _RESPONSE_SCHEMA},
        )
        parsed = json.loads(response.choices[0].message.content)

        for item in parsed["keywords"]:
            legal_basis = {
                "document_id": state["document_id"],
                "article": normalize_article(item["legal_basis"]["article"]),
                "quote": item["legal_basis"]["quote"],
            }
            fields = {**item, "legal_basis": legal_basis}
            drafts.append({"stage": "A", "fields": fields, "legal_basis": legal_basis})

    return {"drafts": drafts}
