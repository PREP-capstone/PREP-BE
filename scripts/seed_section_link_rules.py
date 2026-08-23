"""section_link_rules 1차 시드. 판정엔진_개발설계서.md §15.8.

condition_type별 매칭 대상:
- gate_verdict → judge_gate().verdict (PASS/CONDITIONAL/FAIL)
- data_type    → judge_gate().data_type (생체지표/라이프스타일)
- service_type → 세션의 service_type (앱단독/웨어러블연동/기기연동/오프라인결합,
                 service_law_map과 같은 4종 값을 그대로 씀)

재실행해도 안전하다(있으면 갱신, 없으면 삽입).

    python scripts/seed_section_link_rules.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.models import SectionLinkRule
from app.db.session import AsyncSessionLocal

ROWS = [
    {
        "rule_id": "link_gate_fail_to_regulatory",
        "condition_type": "gate_verdict",
        "condition_value": "FAIL",
        "target_section": "SECTION 2-1 규제 위험도",
        "message": "GATE FAIL 판정입니다. 규제 위험도 섹션에서 판정 근거와 교정 후보를 먼저 확인하세요.",
    },
    {
        "rule_id": "link_gate_conditional_to_regulatory",
        "condition_type": "gate_verdict",
        "condition_value": "CONDITIONAL",
        "target_section": "SECTION 2-1 규제 위험도",
        "message": "조건부 통과(CONDITIONAL) 상태입니다. 규제 위험도 섹션의 판단근거를 함께 검토하세요.",
    },
    {
        "rule_id": "link_gate_pass_to_market",
        "condition_type": "gate_verdict",
        "condition_value": "PASS",
        "target_section": "SECTION 2-3 시장 현실성",
        "message": "GATE PASS 상태입니다. 시장 현실성·수익 구조 섹션에서 사업성을 이어서 검토하세요.",
    },
    {
        "rule_id": "link_biomarker_to_gate",
        "condition_type": "data_type",
        "condition_value": "생체지표",
        "target_section": "SECTION 1 GATE",
        "message": "생체지표 데이터를 다루는 서비스입니다. GATE 판정 결과에서 침습적 하드체크 해당 여부를 확인하세요.",
    },
    {
        "rule_id": "link_biomarker_to_privacy",
        "condition_type": "data_type",
        "condition_value": "생체지표",
        "target_section": "SECTION 2-1 규제 위험도",
        "message": "생체지표는 개인정보 민감도가 높게 산정될 수 있습니다. 규제 위험도 섹션의 민감도 점수를 참고하세요.",
    },
    {
        "rule_id": "link_lifestyle_to_market",
        "condition_type": "data_type",
        "condition_value": "라이프스타일",
        "target_section": "SECTION 2-3 시장 현실성",
        "message": "라이프스타일 데이터 기반 서비스는 시장 경쟁이 치열한 편입니다. 시장 현실성 섹션의 포화도를 확인하세요.",
    },
    {
        "rule_id": "link_device_sync_to_regulatory",
        "condition_type": "service_type",
        "condition_value": "기기연동",
        "target_section": "SECTION 2-1 규제 위험도",
        "message": "기기 연동 서비스는 침습적 신호와 결합되면 GATE FAIL 하드체크 대상이 될 수 있습니다.",
    },
    {
        "rule_id": "link_wearable_to_market",
        "condition_type": "service_type",
        "condition_value": "웨어러블연동",
        "target_section": "SECTION 2-3 시장 현실성",
        "message": "웨어러블 연동 서비스의 경쟁사·수익 구조는 시장 현실성 섹션에서 확인하세요.",
    },
]


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        for row in ROWS:
            existing = await session.get(SectionLinkRule, row["rule_id"])
            if existing is None:
                session.add(SectionLinkRule(**row))
            else:
                existing.condition_type = row["condition_type"]
                existing.condition_value = row["condition_value"]
                existing.target_section = row["target_section"]
                existing.message = row["message"]
        await session.commit()

    print(f"section_link_rules : {len(ROWS)}행")


if __name__ == "__main__":
    asyncio.run(seed())
