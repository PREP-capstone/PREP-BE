"""생명윤리법에서 확인된 질병명 키워드를 gate_keywords(DATA_TYPE)에 시딩한다
(db_구축_설계서.md §1.5 LAW-BIOETHICS-01).

배경: 2026-09-14 Stage A 파이프라인(scripts/run_pipeline.py)을 이 문서(법률 제21065호)에
실제로 돌려봤다(LLM 호출 90회, dry-run 아님, DB 미적재 상태로 결과만 확인). 그 결과 아래
4건이 `type=DISEASE`/`keyword_category=DATA_TYPE`/`weight=4`/`verdict=FAIL_CANDIDATE`로
추출됐다 — 단순 질병명 키워드라 LLM 판단을 그대로 신뢰해 수기로 재시딩한다("유전자검사"처럼
verdict를 올릴 근거가 없음, 그건 seed_genetic_test_keywords.py가 별도로 다룸).

| 키워드 | 근거 조문(LLM 추출) |
|---|---|
| 근이영양증 | 제29조 — "근이영양증(筋異營養症), 그 밖에 대통령령으로 정하는 희귀ㆍ난치병의 치료를 위한 연구" |
| 유전자 | 제6장(장 제목) — "유전자치료 및 검사 등" |
| 유전질환 | 제47조 — "유전질환, 암, 후천성면역결핍증, 그 밖에 생명을 위협하거나 심각한 장애를 불러일으키는 질병" |
| 후천성면역결핍증 | 제47조 — 위와 동일 조문 |

같은 파이프라인 실행에서 함께 나온 "유전자검사"(PROHIBITED_ACTION, legal_basis가 제68조
벌칙조항으로 잘못 잡힘 — 원 후보 18건 중 11건이 여러 조문에 중복 등장해 탈락하면서 하필
벌칙조항만 남았다)와 "질병의 진단"(다른 법령 문서에서 이미 다뤄질 가능성이 높은 범용 표현)은
의도적으로 제외한다 — 2026-09-14 팀 논의로 1순위(기존 수기 시딩 유지 + DATA_TYPE만 추가)
채택.

이 4건이 실제로 쓰이는 경로 두 가지:
- `app/domain/health_data.py` `load_biomarker_keywords()` — gate_keywords(DATA_TYPE) 전체를
  실시간 조회하므로 이 시딩만으로 자동 반영된다(코드 변경 불필요).
- `judgement.py` `_match_gate_keywords()` — regulatory_score 매칭에도 keyword_category와
  무관하게 전체 스캔되므로 함께 반영된다.

"유전자"는 이미 `correction_terms.BIOMARKER_EXTRA`에도 있다(2026-09-14 별도 추가, 분류
버그 수정용). 그건 `_classify_data_type()` 전용 Python 상수라 regulatory_score 매칭
(DB 조회 기반)에는 안 걸린다 — 이 시딩과 역할이 겹치지 않고 상호 보완적이다.

    python scripts/seed_bioethics_disease_keywords.py
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

BIOETHICS_DISEASE_KEYWORDS: tuple[str, ...] = (
    "근이영양증",
    "유전자",
    "유전질환",
    "후천성면역결핍증",
)

DISEASE_ROWS = [{"keyword": keyword, "weight": 4} for keyword in BIOETHICS_DISEASE_KEYWORDS]

COMMON_FIELDS = {
    "type": "DISEASE",
    "keyword_category": "DATA_TYPE",
    "data_type_focus": "NONE",
    "verdict": "FAIL_CANDIDATE",  # Stage A LLM 판단 그대로 — 수기로 올리지 않는다.
}

# gate_keywords에는 legal_basis 컬럼이 없어 publish가 이 값을 쓰지 않는다. 드래프트 형식을
# 맞추기 위한 자리표시자 — 실제 조문은 위 docstring 표 참조(RAG 미수집 상태는 동일).
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
    missing = [row for row in DISEASE_ROWS if row["keyword"].lower() not in existing]

    if not missing:
        print(f"gate_keywords: 이미 active에 {len(DISEASE_ROWS)}행 존재 — 변경 없음")
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
