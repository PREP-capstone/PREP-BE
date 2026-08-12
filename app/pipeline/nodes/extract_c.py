"""[4]+[5]+[5.5] Stage C 프롬프트 주입 + LLM 호출 + 파생값 계산 노드.

산출 축은 `regulatory_score`(gate_keywords 조회 파생) · `advertising_score`(LLM 독립추출) **2축**이다.
privacy_score는 2026-07-28 결정으로 런타임(판정엔진) 계산으로 이관돼 여기서 산출하지 않는다
(db_구축_설계서.md §3.3.2). 최종 위험등급(3축 최고값) 산출도 같은 이유로 런타임 범위다.
"""

import json

from openai import AsyncOpenAI
from sqlalchemy import select

from app.core.config import settings
from app.db.models import GateKeyword, RuleVersion
from app.db.session import AsyncSessionLocal
from app.pipeline.article_ref import (
    ARTICLE_NOTATION_PROMPT,
    build_chunk_message,
    normalize_article,
)
from app.pipeline.state import ExtractedDraft, PipelineState

_RESPONSE_SCHEMA = {
    "name": "gate_c_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "correction_entries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "risky_text": {"type": "string"},
                        "safe_text": {"type": "string"},
                        "advertising_score": {"type": "integer"},
                        "advertising_basis": {
                            "type": "object",
                            "properties": {
                                "attachment7_item": {"type": "integer"},
                                "quote": {"type": "string"},
                            },
                            "required": ["attachment7_item", "quote"],
                            "additionalProperties": False,
                        },
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
                        "risky_text",
                        "safe_text",
                        "advertising_score",
                        "advertising_basis",
                        "legal_basis",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["correction_entries"],
        "additionalProperties": False,
    },
}

_SYSTEM_PROMPT = """당신은 의료용 앱 판단 가이드/법령 조문에서 correction_rules(위험표현·교정) 후보를
추출하는 전문가입니다. 주어진 조문 텍스트를 읽고, 위험 표현(동사×명사 결합) 후보를 0개 이상
추출하세요. 관련 내용이 없으면 correction_entries를 빈 배열로 반환하세요.

## risky_text 후보 힌트 (위험 표현 목록)
- 동사(진단단계): 진단하다, 검사하다, 판별하다, 측정하다(질환 맥락)
- 동사(치료단계): 치료하다, 처방하다, 예방하다, 개선하다, 완화하다, 처치하다, 보정하다
- 명사: 질병명(예: 당뇨, 암, 부정맥 등 DISEASE류 키워드), 생체지표(예: 혈당, 혈압, 심전도, 산소포화도)
- risky_text는 이 동사×명사 결합 형태로 뽑으세요 (예: "당뇨 진단", "혈압 치료"). safe_text는 의료
  행위 표현을 웰니스 범위로 바꾼 대체 표현을 제시하세요 (예: "당뇨 진단" → "혈당 변화 확인").

## advertising_score (별표7 기반, 당신이 직접 판단하는 유일한 축)
의료기기법 제24조제2항("누구든지")+시행규칙 제45조+별표7 기준으로 0~3점을 직접 매기세요.
- 3점: 거짓·과대광고, 확실히 보증한다, 최고/최상, 임상자료·논문·특허 거짓인용, 체험담·구매쇄도 표현,
  미승인 효능 언급, 절대적 표현, 심의미필
- 2점: 오인 유발(부작용 부정·안전성 과장, 전문가 보증·지정·공인 오인, 의료기기 아닌 것으로 오인)
- 1점: 암시적 방법(암시적 기사·사진·도안, 사용전후 비교암시)
- 0점: 해당 없음
advertising_basis.attachment7_item에는 위 기준이 해당하는 별표7 항목 번호(1~18)를, quote에는
그 판단 근거가 되는 원문 문장을 그대로 인용하세요.

## 개인정보 민감도는 추출 대상이 아닙니다
privacy_score는 2026-07-28 결정으로 런타임(판정엔진) 계산으로 이관됐습니다. 값이 위험표현이 아니라
사용자가 선택한 수집 항목에서 결정되기 때문입니다. 개인정보·동의 관련 신호는 추출하지 마세요.

## legal_basis
- article: 이 위험표현 판단의 근거가 되는 조문 번호/제목
- quote: 판단 근거가 되는 원문 문장을 그대로 인용 (반드시 아래 조문 텍스트 안에 실제로 존재하는 문장이어야 함. 지어내지 말 것)

""" + ARTICLE_NOTATION_PROMPT


def _build_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key)


async def extract_C(state: PipelineState) -> dict:
    client = _build_client()
    drafts: list[ExtractedDraft] = list(state["drafts"])
    active_keywords = await _load_active_keywords()

    for chunk in state["chunks"]:
        if not chunk["content"].strip():
            continue

        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": build_chunk_message(chunk)},
            ],
            response_format={"type": "json_schema", "json_schema": _RESPONSE_SCHEMA},
        )
        parsed = json.loads(response.choices[0].message.content)

        for item in parsed["correction_entries"]:
            risky_text = item["risky_text"]
            regulatory_score, derived_from_keyword_id = _derive_regulatory_score(
                risky_text, active_keywords
            )

            legal_basis = {
                "document_id": state["document_id"],
                "article": normalize_article(item["legal_basis"]["article"]),
                "quote": item["legal_basis"]["quote"],
            }
            fields = {
                "risky_text": risky_text,
                "safe_text": item["safe_text"],
                "regulatory_score": regulatory_score,
                "advertising_score": item["advertising_score"],
                "advertising_basis": item["advertising_basis"],
                "derived_from_keyword_id": derived_from_keyword_id,
                "legal_basis": legal_basis,
            }
            drafts.append({"stage": "C", "fields": fields, "legal_basis": legal_basis})

    return {"drafts": drafts}


async def _load_active_keywords() -> list[GateKeyword]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(GateKeyword)
            .join(RuleVersion, RuleVersion.rule_version_id == GateKeyword.rule_version_id)
            .where(RuleVersion.status == "active")
        )
        return list(result.scalars().all())


def _keyword_score(keyword_row: GateKeyword) -> int:
    if keyword_row.weight == 5 or keyword_row.verdict == "FAIL_CONFIRMED":
        return 3
    if keyword_row.weight in (3, 4):
        return 2
    if keyword_row.weight in (1, 2):
        return 1
    return 0


def _derive_regulatory_score(risky_text: str, active_keywords: list[GateKeyword]) -> tuple[int, str | None]:
    best_score = 0
    best_keyword_id = None
    for keyword_row in active_keywords:
        if keyword_row.keyword and keyword_row.keyword in risky_text:
            score = _keyword_score(keyword_row)
            if score > best_score:
                best_score = score
                best_keyword_id = str(keyword_row.keyword_id)
    return best_score, best_keyword_id
