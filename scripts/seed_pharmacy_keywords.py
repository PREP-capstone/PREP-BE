"""약무행위 키워드를 gate_keywords에 시딩한다 (db_구축_설계서.md §1.5 LAW-PHARM-01).

배경: 약무행위(처방·조제·복약지도)를 correction_rules의 4번째 축으로 신설하지 않고
`regulatory_score`에 흡수하기로 확정했다. 그런데 gate_keywords에 약무 키워드가 없으면
Stage C의 `_derive_regulatory_score`가 매칭할 대상이 없어 "맞춤형 영양제 처방" 같은 표현이
0점으로 통과해버린다 (구현_현황_정리.md §Stage A 추가 구현 필요).

**적재는 publish()를 거친다** — 직접 INSERT하지 않는다. 누적 발행(B안)으로 바뀐 뒤에는
publish()가 기존 active 행을 승계하므로, 시드도 같은 경로를 타야 이후 문서 투입 때
자동으로 승계된다. 예전처럼 자체 rule_version에 직접 넣으면 다음 publish에서
승계 대상으로 잡히긴 하나, 발행 이력이 파이프라인과 따로 놀아 추적이 어려워진다.

결정 사항:
- `keyword_category`: 신규 분류를 만들지 않고 기존 **TREATMENT를 재사용**한다. 약무행위는
  "처치·개선·예방을 지시·유도하는 단계"라는 TREATMENT 정의에 그대로 들어맞고, enum을
  늘리면 validate.py·판정엔진·설계서를 함께 고쳐야 한다.
- `weight=4` / `verdict=FAIL_CONFIRMED` (2026-08-12 C안 확정) → Stage C에서
  regulatory_score **3점(높음)**이 된다. 산출식이 "weight=5 **또는**
  verdict=FAIL_CONFIRMED → 3점"이라, weight 5의 정의("고위해도 5요소 전용")를 건드리지 않고도
  무면허 약무행위를 무면허 의료행위(진단·치료)와 동일 급으로 평가할 수 있다.

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

if hasattr(sys.stdout, "reconfigure"):  # 한글 출력이 콘솔 코드페이지에 깨지지 않도록
    sys.stdout.reconfigure(encoding="utf-8")

from app.db.models import GateKeyword, RuleVersion
from app.db.session import AsyncSessionLocal
from app.pipeline.nodes.publish import publish
from app.pipeline.pharmacy_actions import PHARMACY_ACTION_KEYWORDS

# 키워드 목록은 app/pipeline/pharmacy_actions.py가 단일 출처다 — validate.py의
# FAIL_CONFIRMED 인정 범위와 어긋나면 시드가 검증을 통과하지 못한다.
PHARMACY_KEYWORDS = [{"keyword": keyword, "weight": 4} for keyword in PHARMACY_ACTION_KEYWORDS]

COMMON_FIELDS = {
    "type": "PROHIBITED_ACTION",
    "keyword_category": "TREATMENT",
    "data_type_focus": "NONE",  # 약무행위는 입력 포맷과 무관
    "verdict": "FAIL_CONFIRMED",
}

# gate_keywords에는 legal_basis 컬럼이 없어 publish가 이 값을 쓰지 않는다.
# 드래프트 형식을 맞추기 위한 자리표시자다.
_LEGAL_BASIS = {
    "document_id": "kr-pharmaceutical-affairs-act-20260621",
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
    missing = [row for row in PHARMACY_KEYWORDS if row["keyword"].lower() not in existing]

    if not missing:
        print(f"gate_keywords: 이미 active에 {len(PHARMACY_KEYWORDS)}행 존재 — 변경 없음")
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
