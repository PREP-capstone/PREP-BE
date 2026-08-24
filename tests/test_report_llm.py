"""LLM②(차별화 포인트)·LLM③(BM 카드 강점 요약) 회귀 테스트.

실제 OpenAI 호출이 필요한 케이스는 @pytest.mark.llm으로 표시한다(비용 발생) —
`-m "not llm"`으로 제외 가능(CI 기본값). 키 없이도 확인 가능한 그레이스풀
디그레이드 경로는 마커 없이 항상 돈다.
"""

import pytest

from app.domain import report_llm
from app.domain.report_llm import LLMUnavailable, generate_bm_card_strengths, generate_differentiation_point


async def test_generate_differentiation_point_raises_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(report_llm.settings, "openai_api_key", "")
    with pytest.raises(LLMUnavailable):
        await generate_differentiation_point("테스트 서비스", [])


async def test_generate_bm_card_strengths_returns_empty_without_calling_when_no_recommendations() -> None:
    # recommendations가 비어있으면 클라이언트 생성조차 안 하고 바로 빈 dict —
    # OPENAI_API_KEY 유무와 무관하게 항상 통과해야 한다.
    result = await generate_bm_card_strengths("테스트 서비스", [])
    assert result == {}


@pytest.mark.llm
async def test_generate_differentiation_point_real_call() -> None:
    point = await generate_differentiation_point(
        "매일 걸음수와 심박수를 기록하고 그래프로 보여주는 앱",
        [
            {"name": "삼성헬스", "limitation": "삼성 기기 사용자만 완전한 기능을 쓸 수 있음"},
            {"name": "구글핏", "limitation": "그래프가 단순해 세부 분석이 어려움"},
        ],
    )
    assert isinstance(point, str)
    assert len(point) > 0


@pytest.mark.llm
async def test_generate_bm_card_strengths_real_call_matches_input_patterns() -> None:
    recommendations = [
        {"bm_pattern": "Freemium(프리미엄)", "contributing_competitor_ids": "삼성헬스, 구글핏"},
    ]
    strengths = await generate_bm_card_strengths(
        "매일 걸음수와 심박수를 기록하고 그래프로 보여주는 앱", recommendations
    )
    assert "Freemium(프리미엄)" in strengths
    assert isinstance(strengths["Freemium(프리미엄)"], str)
    assert len(strengths["Freemium(프리미엄)"]) > 0
