"""DTC 유전자검사 키워드를 gate_keywords에 시딩한다 (db_구축_설계서.md §1.5 LAW-BIOETHICS-01).

배경: 2026-09-14 확인 — legal_documents.py가 흡수하는 8개 법령 문서 중 「생명윤리 및 안전에
관한 법률」이 없어, 유전자검사 서비스가 DTC(소비자 직접 의뢰) 인증 대상인지 판정할 근거가
게이트 로직에 아예 없었다. 약사법(LAW-PHARM-01, v1.9)을 추가했던 것과 같은 방식 —
gate_keywords에 키워드를 시딩해 기존 Stage A 스캔(judgement.py `_match_gate_keywords`)이
service_description에서 직접 감지하게 한다. category_1(시장축)로 트리거하지 않는 이유는
genetic_test_actions.py 참고 — category_1과 규제판정축(data_type/function_type)은 설계상
분리돼 있어(§3.5) 카테고리 값 하나로 게이트를 걸면 오탐/누락이 생긴다.

**RAG 미확보 상태에서도 시딩 가능한 이유**: gate_keywords에는 애초에 legal_basis 저장
컬럼이 없다(seed_pharmacy_keywords.py와 동일). `_match_gate_keywords`→`keyword_score`
경로는 이 컬럼 없이도 동작하므로, RAG에 생명윤리법 원문이 수집되기 전에도 regulatory_score는
정상적으로 반영된다 — 다만 matched_rules에 근거 조문이 노출되진 않는다(correction_rules
경로만 legal_basis를 노출, §8.2 LAW-BIOETHICS-01 항목에 알려진 제약으로 기록됨).

결정 사항:
- `keyword_category`: DIAGNOSIS("진단")·TREATMENT("처치·개선·예방을 지시·유도")
  어느 정의에도 깔끔히 들어맞지 않아(이 키워드가 잡으려는 건 "인증 없이 제공하는 행위"
  자체지 진단·처치 표현이 아님) **OTHER**를 쓴다 — validate.py enum 통과 여부에만
  영향을 주는 태그라 기능적 차이는 없다.
- `weight=4` / `verdict=FAIL_CONFIRMED` — 약무행위와 같은 근거(2026-08-12 C안)로
  weight=5("고위해도 5요소 전용")를 건드리지 않고 regulatory_score 3점(높음)에 도달한다.

    python scripts/seed_genetic_test_keywords.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):  # 한글 출력이 콘솔 코드페이지에 깨지지 않도록
    sys.stdout.reconfigure(encoding="utf-8")

from app.db.models import GateKeyword, RuleVersion
from app.db.session import AsyncSessionLocal
from app.pipeline.genetic_test_actions import GENETIC_TEST_KEYWORDS
from app.pipeline.nodes.publish import publish

GENETIC_TEST_ROWS = [{"keyword": keyword, "weight": 4} for keyword in GENETIC_TEST_KEYWORDS]

COMMON_FIELDS = {
    "type": "PROHIBITED_ACTION",
    "keyword_category": "OTHER",
    "data_type_focus": "NONE",  # 유전자검사 제공 여부는 입력 포맷과 무관
    "verdict": "FAIL_CONFIRMED",
}

# gate_keywords에는 legal_basis 컬럼이 없어 publish가 이 값을 쓰지 않는다. 드래프트 형식을
# 맞추기 위한 자리표시자 — document_id는 아직 없다(RAG 미수집, §8.2 LAW-BIOETHICS-01).
_LEGAL_BASIS = {
    "document_id": "",
    "article": "",
    "quote": "",
}


async def _active_keywords() -> set[str]:
    async with AsyncSessionLocal() as session:
        rows = await session.scalars(
            select(func.lower(GateKeyword.keyword))
            .join(RuleVersion, RuleVersion.rule_version_id == GateKeyword.rule_version_id)
            .where(RuleVersion.status == "active")
        )
        return set(rows.all())


async def seed() -> None:
    existing = await _active_keywords()
    missing = [row for row in GENETIC_TEST_ROWS if row["keyword"].lower() not in existing]

    if not missing:
        print(f"gate_keywords: 이미 active에 {len(GENETIC_TEST_ROWS)}행 존재 — 변경 없음")
        return

    drafts = [
        {
            "stage": "A",
            "fields": {
                "keyword": row["keyword"],
                "weight": row["weight"],
                "legal_basis": _LEGAL_BASIS,
                **COMMON_FIELDS,
            },
            "legal_basis": _LEGAL_BASIS,
        }
        for row in missing
    ]
    result = await publish({"drafts": drafts, "rule_version_id": None})

    async with AsyncSessionLocal() as session:
        version = await session.scalar(
            select(RuleVersion.version).where(
                RuleVersion.rule_version_id == result["rule_version_id"]
            )
        )
    print(f"gate_keywords: {len(drafts)}행 발행 (신규 rule_version={version}, 기존 active 승계 포함)")


if __name__ == "__main__":
    asyncio.run(seed())
