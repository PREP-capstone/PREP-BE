from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GateKeyword
from app.db.rule_version_queries import ACTIVE_RULE_VERSION_IDS
from app.pipeline.correction_terms import BIOMARKER_EXTRA
from app.pipeline.genetic_test_actions import GENETIC_TEST_KEYWORDS

SOURCE_TO_ACQUIRE_METHOD = {
    "user_input": "수동입력",
    "device_sync": "기기연동",
    "os_sync": "OS연동",
    "institution_sync": "기관연동",
}


# gate_keywords(DATA_TYPE) 중 GATE 생체지표 판별에 실제로 써도 되는 것만 화이트리스트로 제한.
# DATA_TYPE 카테고리는 Stage C 명사풀(correction_terms.NOUN_CLASSIFICATION)과 공유되는
# 원천이라 전체를 그대로 쓰면 질병명(고혈압/당뇨 등)과 GATE 기준 라이프스타일(수면/스트레스/
# 정신적 안정 — db_구축_설계서.md §3.2, data_sensitivity의 lifestyle_002/005)까지 생체지표로
# 새어 들어와 GATE 오분류가 난다(2026-09-27 백엔드 이슈로 확인). NOUN_CLASSIFICATION도 이
# 목적과 분류 기준이 달라(수면/스트레스를 "생체지표"로 분류) 그대로 재사용할 수 없다 —
# 자동 판별 대신 수기 화이트리스트로 막는다.
_GATE_BIOMARKER_DATA_TYPE_KEYWORDS = frozenset({"혈당", "혈압", "체온", "체지방"})


async def load_biomarker_keywords(session: AsyncSession) -> set[str]:
    """생체지표 판별 사전 = gate_keywords(DATA_TYPE) 중 화이트리스트 + 보정용 기본 지표.

    GENETIC_TEST_KEYWORDS는 BIOMARKER_EXTRA에 안 넣고 여기서 따로 union한다 —
    BIOMARKER_EXTRA는 generate_correction_rules.py가 통째로 noun pool에 넣어 모든
    verb_substitution 동사와 조합하므로, 거기에 "유전자" 같은 짧은 명사를 넣으면 의료기기법
    동사와 조합돼 legal_basis가 어긋난 correction_rules가 생긴다(2026-09-14 발견).
    GENETIC_TEST_KEYWORDS는 "유전자검사"처럼 이미 구체적인 복합어라 "유전자변형식품" 같은
    무관한 항목명을 오탐하지도 않는다.
    """
    result = await session.execute(
        select(GateKeyword.keyword).where(
            GateKeyword.rule_version_id.in_(ACTIVE_RULE_VERSION_IDS),
            GateKeyword.keyword_category == "DATA_TYPE",
        )
    )
    keywords = {
        keyword
        for keyword in result.scalars().all()
        if keyword and keyword in _GATE_BIOMARKER_DATA_TYPE_KEYWORDS
    }
    return keywords | set(BIOMARKER_EXTRA) | set(GENETIC_TEST_KEYWORDS)


def is_biomarker_name(name: str, biomarker_keywords: set[str]) -> bool:
    return any(keyword in name for keyword in biomarker_keywords)
