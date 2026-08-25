"""LLM②(차별화 포인트)·LLM③(BM 카드 강점 요약) — 판정엔진_개발설계서.md §12.

§10.1과 같은 원칙: 판정(verdict/등급/신호등)에는 영향 없음 — 순수 리포트 서술
콘텐츠 생성용이다. OPENAI_API_KEY가 없거나 호출이 실패하면 LLMUnavailable을
올린다. evaluate.py가 이를 잡아 해당 필드만 None/빈 값으로 채운다 — 나머지
리포트는 계속 만들어진다(§12 "관리 원칙"과 별개로, 리포트 조립 자체가 LLM
장애로 전부 죽으면 안 된다는 이 프로젝트의 일반 원칙을 따른다).

app/pipeline/nodes/extract_a.py와 같은 OpenAI 호출 패턴(AsyncOpenAI +
response_format=json_schema)을 그대로 따른다.
"""

from __future__ import annotations

import json

import openai
from openai import AsyncOpenAI

from app.core.config import settings


class LLMUnavailable(Exception):
    """OPENAI_API_KEY 미설정 또는 호출 실패 시."""


def _build_client() -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise LLMUnavailable("OPENAI_API_KEY가 설정되지 않았습니다.")
    return AsyncOpenAI(api_key=settings.openai_api_key)


_DIFFERENTIATION_SCHEMA = {
    "name": "differentiation_point",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"differentiation_point": {"type": "string"}},
        "required": ["differentiation_point"],
        "additionalProperties": False,
    },
}

_DIFFERENTIATION_SYSTEM_PROMPT = """당신은 헬스케어 스타트업 시장 분석가입니다.
주어진 서비스 설명과 경쟁 서비스 목록(이름·한계)을 보고, 이 서비스가 경쟁사 대비
가질 수 있는 차별화 포인트를 1~2문장으로 제안하세요.

원칙:
- 경쟁사의 "한계"로 제시된 부분을 파고드는 방향으로 제안하세요.
- 근거 없는 낙관적 주장(예: "무조건 성공한다")을 하지 마세요.
- 경쟁사 목록이 없거나 부족하면 일반적인 원칙(사용자 경험, 데이터 품질 등)에서 제안하세요.
"""


async def generate_differentiation_point(service_description: str, competitor_cards: list[dict]) -> str:
    """SECTION 2-3 "차별화 포인트" (판정엔진_개발설계서.md §12 LLM②)."""
    client = _build_client()
    competitors_text = (
        "\n".join(
            f"- {c['name']}: 한계 - {c.get('limitation') or '정보 없음'}" for c in competitor_cards
        )
        or "(매칭된 경쟁사 없음)"
    )

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _DIFFERENTIATION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"서비스 설명: {service_description}\n\n경쟁 서비스:\n{competitors_text}",
                },
            ],
            response_format={"type": "json_schema", "json_schema": _DIFFERENTIATION_SCHEMA},
        )
        parsed = json.loads(response.choices[0].message.content)
        return parsed["differentiation_point"]
    except (openai.OpenAIError, json.JSONDecodeError, KeyError, IndexError, AttributeError) as error:
        # 레이트리밋·타임아웃·malformed JSON 등 실제 호출 실패도 LLMUnavailable로 통일한다 —
        # 이게 없으면 evaluate.py의 except LLMUnavailable을 뚫고 올라가 /evaluate 전체가
        # 500으로 죽는다(코드 리뷰로 확인된 실제 버그, 2026-08-25).
        raise LLMUnavailable(f"차별화 포인트 생성 실패: {error}") from error


_BM_STRENGTH_SCHEMA = {
    "name": "bm_card_strengths",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "cards": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "bm_pattern": {"type": "string"},
                        "strength": {"type": "string"},
                    },
                    "required": ["bm_pattern", "strength"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["cards"],
        "additionalProperties": False,
    },
}

_BM_STRENGTH_SYSTEM_PROMPT = """당신은 헬스케어 스타트업 수익모델(BM) 컨설턴트입니다.
주어진 서비스 설명과 추천된 BM(수익모델) 후보 목록을 보고, 각 BM이 이 서비스에
왜 적합한지 강점을 1문장으로 요약하세요. 입력받은 cards와 같은 개수·순서로,
같은 bm_pattern 값을 그대로 포함해 응답하세요.

원칙:
- 근거 없는 수치(전환율·매출 예측 등)를 만들어내지 마세요.
- bm_pattern의 일반적 특성 + 이 서비스의 성격을 연결해서 설명하세요.
"""


async def generate_bm_card_strengths(service_description: str, recommendations: list[dict]) -> dict[str, str]:
    """SECTION 2-4 "BM 카드 강점" (판정엔진_개발설계서.md §12 LLM③, §9.3).

    반환값은 bm_pattern → strength 매핑이다. 가격대(competitors.price)·전환율은
    이 함수 밖(DB 조회/데이터 부재)에서 처리한다 — §9.3 "카드 4줄 요약의 데이터
    부족" 표 참고, LLM이 만드는 건 강점 한 줄뿐이다.
    """
    if not recommendations:
        return {}

    client = _build_client()
    cards_text = "\n".join(
        f"- BM: {r['bm_pattern']}, 참고 경쟁사: {r.get('contributing_competitor_ids') or '없음'}"
        for r in recommendations
    )

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _BM_STRENGTH_SYSTEM_PROMPT},
                {"role": "user", "content": f"서비스 설명: {service_description}\n\nBM 후보:\n{cards_text}"},
            ],
            response_format={"type": "json_schema", "json_schema": _BM_STRENGTH_SCHEMA},
        )
        parsed = json.loads(response.choices[0].message.content)
        return {card["bm_pattern"]: card["strength"] for card in parsed["cards"]}
    except (openai.OpenAIError, json.JSONDecodeError, KeyError, IndexError, AttributeError) as error:
        raise LLMUnavailable(f"BM 카드 강점 생성 실패: {error}") from error
