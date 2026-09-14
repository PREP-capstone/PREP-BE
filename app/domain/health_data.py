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


async def load_biomarker_keywords(session: AsyncSession) -> set[str]:
    """생체지표 판별 사전 = gate_keywords(DATA_TYPE) + 보정용 기본 지표.

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
    keywords = {keyword for keyword in result.scalars().all() if keyword}
    return keywords | set(BIOMARKER_EXTRA) | set(GENETIC_TEST_KEYWORDS)


def is_biomarker_name(name: str, biomarker_keywords: set[str]) -> bool:
    return any(keyword in name for keyword in biomarker_keywords)
