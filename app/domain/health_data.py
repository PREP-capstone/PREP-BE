from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GateKeyword
from app.db.rule_version_queries import ACTIVE_RULE_VERSION_IDS
from app.pipeline.correction_terms import BIOMARKER_EXTRA, NOUN_CLASSIFICATION
from app.pipeline.genetic_test_actions import GENETIC_TEST_KEYWORDS

SOURCE_TO_ACQUIRE_METHOD = {
    "user_input": "수동입력",
    "device_sync": "기기연동",
    "os_sync": "OS연동",
    "institution_sync": "기관연동",
}


# gate_keywords(DATA_TYPE)에서 GATE 생체지표 판별에 쓰면 안 되는 키워드 블랙리스트.
# 판정엔진_개발설계서.md §5.1은 "생체지표 판별 사전은 gate_keywords(DATA_TYPE) 전체를 그대로
# 쓰고, 문서가 추가되면 자동으로 늘어난다"고 설계돼 있다 — 화이트리스트로 막으면 이 자동 확장이
# 깨져서 향후 파이프라인이 새로 추출한 진짜 생체지표 키워드까지 수동으로 여기 추가하기 전엔
# GATE에 반영이 안 된다. 그래서 화이트리스트 대신, NOUN_CLASSIFICATION에서 "질병명"으로 분류된
# 키워드(고혈압/당뇨 등)만 블랙리스트로 제외한다.
# 수면/스트레스/정신적 안정은 NOUN_CLASSIFICATION에도 "생체지표"로 분류돼 있지만 그건 Stage C
# 명사풀 전용 분류 기준이고, GATE 기준으로는 라이프스타일이다(db_구축_설계서.md §3.2,
# data_sensitivity의 lifestyle_002/005) — 이 세 개는 별도로 블랙리스트에 추가한다
# (2026-09-27 백엔드 이슈로 확인).
_GATE_NON_BIOMARKER_DATA_TYPE_KEYWORDS = frozenset(
    keyword for keyword, category in NOUN_CLASSIFICATION.items() if category == "질병명"
) | frozenset({"수면", "스트레스", "정신적 안정"})


async def load_biomarker_keywords(session: AsyncSession) -> set[str]:
    """생체지표 판별 사전 = gate_keywords(DATA_TYPE) 중 블랙리스트 제외 + 보정용 기본 지표.

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
        if keyword and keyword not in _GATE_NON_BIOMARKER_DATA_TYPE_KEYWORDS
    }
    return keywords | set(BIOMARKER_EXTRA) | set(GENETIC_TEST_KEYWORDS)


def is_biomarker_name(name: str, biomarker_keywords: set[str]) -> bool:
    return any(keyword in name for keyword in biomarker_keywords)
