"""약무행위 키워드를 gate_keywords에 시딩한다 (db_구축_설계서.md §1.5 LAW-PHARM-01, §3.3).

배경: 약무행위(처방·조제·복약지도)를 correction_rules의 4번째 축으로 신설하지 않고
`regulatory_score`에 흡수하기로 확정됐다. 그런데 gate_keywords에 약무 키워드가 없으면
Stage C의 `_derive_regulatory_score`가 매칭할 대상이 없어 "맞춤형 영양제 처방" 같은 표현이
0점으로 통과해버린다 (구현_현황_정리.md §Stage A 추가 구현 필요).

결정 사항 (팀 확인 필요 — 문서에 값이 확정돼 있지 않음):
- `keyword_category`: 신규 분류를 만들지 않고 기존 **TREATMENT를 재사용**한다. 약무행위는
  "처치·개선·예방을 지시·유도하는 단계"라는 TREATMENT 정의에 그대로 들어맞고, enum을 늘리면
  validate.py·판정엔진·설계서를 함께 고쳐야 한다.
- `weight=4` / `verdict=FAIL_CANDIDATE` → Stage C에서 regulatory_score **2점(중간)**이 된다.
  weight 척도상 5는 "고위해도 5요소(침습적·오작동 시 상해 등)" 전용이라 약무행위에 맞지 않고,
  4가 "의료 목적 강하게 암시, 단독 FAIL 후보"로 정의돼 있어 이쪽이 텍스트상 정합적이다.
  ⚠️ 무면허 약무행위를 3점(높음)으로 볼지는 팀 판단이 필요하다 — 그렇게 정하면 weight=5로 올린다.

참고: `gate_keywords`에는 legal_basis 저장 컬럼이 없어 약사법 서지정보를 행에 남길 수 없다
(§15.10 각주, 담당 E 스코프 밖). 근거 문서는 RAG에 이미 수집돼 있다
— `kr-pharmaceutical-affairs-act-20260621` (약사법, 2026-06-21 시행).

    python scripts/seed_pharmacy_keywords.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.models import GateKeyword, RuleVersion
from app.db.session import AsyncSessionLocal

PHARMACY_KEYWORDS = [
    {"keyword": "처방", "weight": 4},
    {"keyword": "조제", "weight": 4},
    {"keyword": "복약지도", "weight": 4},
    {"keyword": "투약", "weight": 4},
]

COMMON_FIELDS = {
    "type": "PROHIBITED_ACTION",
    "keyword_category": "TREATMENT",
    "data_type_focus": "NONE",  # 약무행위는 입력 포맷과 무관
    "verdict": "FAIL_CANDIDATE",
}


async def _gate_keyword_rule_version(session) -> RuleVersion:
    """Stage A 전용 active rule_version을 확보한다 (publish.py의 Stage별 lineage와 동일 원리)."""
    existing = await session.scalar(
        select(RuleVersion)
        .join(GateKeyword, GateKeyword.rule_version_id == RuleVersion.rule_version_id)
        .where(RuleVersion.status == "active")
        .limit(1)
    )
    if existing:
        return existing

    version_count = len((await session.scalars(select(RuleVersion.rule_version_id))).all())
    rule_version = RuleVersion(version=f"v0.{version_count + 1}", status="active")
    session.add(rule_version)
    await session.flush()
    return rule_version


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        rule_version = await _gate_keyword_rule_version(session)
        existing_keywords = {
            row for row in (await session.scalars(select(func.lower(GateKeyword.keyword)))).all()
        }
        inserted = 0

        for row in PHARMACY_KEYWORDS:
            if row["keyword"].lower() in existing_keywords:
                continue
            session.add(
                GateKeyword(
                    rule_version_id=rule_version.rule_version_id,
                    keyword=row["keyword"],
                    weight=row["weight"],
                    **COMMON_FIELDS,
                )
            )
            inserted += 1

        await session.commit()
        print(f"gate_keywords: {inserted}행 신규 적재 (rule_version={rule_version.version})")


if __name__ == "__main__":
    asyncio.run(seed())
