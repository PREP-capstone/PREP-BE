"""LLM① 폴백 — correction-candidates 규칙 기반 매칭이 0건일 때만 보완 호출.
판정엔진_개발설계서.md §12(LLM①).

2026-08-23 실측(자연스러운 문장 10개): 위험 문장 8개 중 4개(복약지도/위험도 분류·트리아지/
정신건강 상담/임산부 모니터링)가 gate_keywords 68개 중 단 하나도 안 걸려 규칙 기반으로
100% 놓쳤다. 전부 실제로 위험한 기능인데 키워드 단어 자체가 문장에 없는 파라프레이즈라
원천적으로 못 잡는 케이스 — 이 모듈이 그 recall 공백을 메운다. 항상 병렬 호출하던 원설계
대신 0건일 때만 도는 폴백으로 축소해 비용을 줄인다(judge_correction_candidates 참조).

app/pipeline/nodes/extract_c.py와 달리 이 모듈은 **법령 조문 텍스트가 아니라 서비스
설명문**을 입력받는다 — 즉 LLM이 인용할 원문이 눈앞에 없으므로 "조문 안에 실제로 있는
문장만 인용" 원칙을 강제할 수 없다. 대신 LLM에게 document_id/article까지 추정하게 하고,
judgement.py의 기존 `_fill_quotes()`(신뢰 문서 화이트리스트 + RAG 조회)에 그대로 태워
보낸다 — 추정이 맞으면 실제 원문이 채워지고, 틀리거나 화이트리스트 밖이면 quote만 None으로
빠진다(에러 아님). 인용 자체를 지어내는 위험은 없다.

OPENAI_API_KEY가 없거나 호출이 실패하면(레이트리밋·타임아웃·malformed 응답 포함)
LLMUnavailable을 올린다. judge_correction_candidates()가 이를 잡아 빈 리스트로 폴백한다 —
§10.1 "LLM 장애로 핵심 응답이 깨지면 안 된다" 원칙과 동일.
"""

from __future__ import annotations

import json

import openai
from openai import AsyncOpenAI

from app.core.config import settings
from app.pipeline.article_ref import normalize_article

# 이 호출은 evaluate.py의 asyncio.gather 안에서 다른 API들과 나란히 대기된다 — 무한정 걸리면
# /evaluate 전체가 그만큼 늘어진다. trend_client.py의 외부 API 타임아웃(10초)과 같은 결.
_REQUEST_TIMEOUT_SECONDS = 15.0

# judgement.py._RAG_TRUSTED_DOCUMENT_IDS와 동일 — LLM이 legal_basis.document_id를 이
# 목록 중에서 고르면 _fill_quotes()가 실제 원문을 채울 수 있다. 목록 밖 값을 내도 에러는
# 아니고 quote만 None으로 빠진다.
_KNOWN_DOCUMENTS = """- kr-mfds-wellness-0091-03-20260212: 모바일 의료용 앱 안전관리 지침(웰니스 판단기준) — 진단·치료·처방 등 의료행위 해당 여부 일반 기준
- kr-pharmaceutical-affairs-act-20260621: 약사법 — 복약지도·조제·투약 안내 등 약무행위
- kr-medical-act-20260407: 의료법 — 무면허 의료행위(진단·치료·처방) 일반
- kr-medical-device-act-20260701: 의료기기법 — 의료기기 해당 여부·인증
- kr-medical-device-act-rule-annex7-20260701: 의료기기법 시행규칙 별표7 — 광고 표현 기준"""

_SYSTEM_PROMPT = f"""당신은 헬스케어 스타트업 서비스 설명문에서 무면허 의료행위·약무행위로
오인될 수 있는 위험 표현을 찾는 전문가입니다. 사전에 정의된 위험 표현 목록과 정확히
일치하는 문구가 없어 규칙 기반 매칭이 이미 실패한 문장만 당신에게 옵니다 — 문장에
개별 키워드가 전혀 안 걸렸을 수도, 걸렸지만 해당 표현에 대한 교정 후보가 아직 없을
수도 있습니다. 어느 쪽이든 의미상 진단·치료·처방·복약지도 등 의료행위를 암시하는
표현이 있는지 새로 판단해주세요.

## 찾아야 할 것
문장에 명시적 위험 키워드가 없어도, 기능 설명이 실질적으로 다음에 해당하면 risky_text로
추출하세요:
- 진단/위험도 판정을 암시 (예: "위험 단계인지 나눠서 알려줍니다", "이상 신호 보이면 안내")
- 복약·투약 지도를 암시 (예: "약 시간표를 짜드려요")
- 상담을 가장한 심리/정신 건강 개입 (예: "마음 상태를 짚어드리고 조언")
- 그 외 진단·치료·처방에 해당하는 기능을 완곡하게 표현한 경우

## risky_text / safe_text
- risky_text: 원문에서 실제로 위험하다고 판단한 부분을 그대로 발췌하세요(지어내지 말 것).
- safe_text: 같은 기능을 의료행위로 오인되지 않게 표현한 대체 문구를 제시하세요
  (예: "위험 단계인지 나눠서 알려줍니다" → "측정값의 변화 추이를 보여드립니다").

## legal_basis (아래 알려진 문서 중에서만 고를 것 — 목록에 없는 문서를 지어내지 말 것)
{_KNOWN_DOCUMENTS}

- document_id: 위 5개 중 이 위험 표현과 가장 관련 있는 문서 하나
- article: 그 문서에서 관련성이 높을 것으로 추정되는 조문 번호(정확히 모르면 최선의 추정값)

## 없으면
위 기준에 해당하는 표현이 전혀 없으면 candidates를 빈 배열로 반환하세요. 억지로 만들어내지
마세요 — 안전한 문장을 위험하다고 잘못 판정하는 것(오탐)이 놓치는 것보다 나쁩니다.
"""

_RESPONSE_SCHEMA = {
    "name": "correction_candidates_fallback",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "risky_text": {"type": "string"},
                        "safe_text": {"type": "string"},
                        "legal_basis": {
                            "type": "object",
                            "properties": {
                                "document_id": {"type": "string"},
                                "article": {"type": "string"},
                            },
                            "required": ["document_id", "article"],
                            "additionalProperties": False,
                        },
                    },
                    "required": ["risky_text", "safe_text", "legal_basis"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["candidates"],
        "additionalProperties": False,
    },
}


class LLMUnavailable(Exception):
    """OPENAI_API_KEY 미설정 또는 호출 실패(레이트리밋·타임아웃·malformed 응답 포함) 시."""


def _build_client() -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise LLMUnavailable("OPENAI_API_KEY가 설정되지 않았습니다.")
    return AsyncOpenAI(api_key=settings.openai_api_key, timeout=_REQUEST_TIMEOUT_SECONDS)


async def generate_correction_candidates(service_description: str) -> list[dict]:
    """규칙 기반(gate_keywords/correction_rules) 매칭이 0건일 때만 호출하는 LLM① 폴백.

    반환값 각 원소는 {"risky_text", "safe_text", "legal_basis": {"document_id", "article"}}.
    article은 extract_a/b/c.py와 동일하게 normalize_article()로 정규화한다 — RAG
    evidence_chunks.section_id와 표기가 안 맞으면 _fill_quotes()의 원문 조회가 그냥 조용히
    실패(quote=None)하므로, 여기서 맞춰두는 편이 quote 채워질 확률을 높인다.
    """
    client = _build_client()
    try:
        # 이 경로는 요청마다(호출 실패 시에도) 매번 새 클라이언트를 만드는 offline
        # extract_a/b/c.py 패턴을 그대로 가져왔지만, 여기는 사용자 요청 경로라 커넥션을
        # 안 닫고 두면 계속 쌓인다 — async with로 확실히 닫는다.
        async with client:
            response = await client.chat.completions.create(
                model=settings.openai_model,
                # extract_a/b/c.py와 같은 이유로 0 고정 — 같은 서비스 설명문에 재시도가 붙었을 때
                # 위험 판정이 흔들리면 규제 관련 판단으로서 신뢰도가 떨어진다.
                temperature=0,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": f"서비스 설명: {service_description}"},
                ],
                response_format={"type": "json_schema", "json_schema": _RESPONSE_SCHEMA},
            )
        parsed = json.loads(response.choices[0].message.content)
        candidates = parsed["candidates"]
    except openai.OpenAIError as error:
        raise LLMUnavailable(f"OpenAI 호출 실패: {error}") from error
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise LLMUnavailable(f"OpenAI 응답 형식이 예상과 다릅니다: {error}") from error

    try:
        for item in candidates:
            item["legal_basis"]["article"] = normalize_article(item["legal_basis"]["article"])
    except (KeyError, TypeError) as error:
        raise LLMUnavailable(f"OpenAI 응답 형식이 예상과 다릅니다: {error}") from error
    return candidates
