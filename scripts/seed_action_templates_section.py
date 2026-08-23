"""action_templates scope=SECTION 1차 시드. 판정엔진_개발설계서.md §15.3.

SECTION 2-1(규제 위험도) "다음 액션 3~4개" + 부록(GATE FAIL)용. 기존 시드(OVERALL 17행,
scope=SECTION 0행)는 data_level/market_level/공통 트리거만 있어 규제·GATE 쪽이 비어
있었다 — 이 스크립트는 gate_verdict/risk_level/sensitivity_level 트리거만 추가한다.

trigger_type별 매칭 대상(evaluate 응답 기준):
- gate_verdict     → judge_gate().verdict (FAIL)
- risk_level       → judge_regulatory_risk().regulatory_grade (낮음/중간/높음)
- sensitivity_level→ judge_regulatory_risk().privacy_score (정수, 문자열로 매칭)

sensitivity_level=3 행은 §15.3의 "필수 시드 액션" 경고를 그대로 반영한 것 — 동의
언급 여부가 privacy_score 산출에서 빠진 대신(db_구축_설계서.md §3.3.2), 별도 동의
요건을 여기서 안내한다.

재실행해도 안전하다(있으면 갱신, 없으면 삽입).

    python scripts/seed_action_templates_section.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.models import ActionTemplate
from app.db.session import AsyncSessionLocal

ROWS = [
    {
        "template_id": "act_gate_fail_1",
        "scope": "SECTION",
        "trigger_type": "gate_verdict",
        "trigger_value": "FAIL",
        "action_text": "GATE FAIL 판정 사유가 된 표현·기능을 제거하거나 재설계한 뒤 재판정을 요청하세요.",
        "ref_doc": None,
        "tag": None,
        "priority": 900,
    },
    {
        "template_id": "act_sens_high_1",
        "scope": "SECTION",
        "trigger_type": "sensitivity_level",
        "trigger_value": "3",
        "action_text": (
            "개인정보 보호법 제23조에 따른 별도 동의가 필요한 민감정보입니다. "
            "일반 이용약관 동의·통합 동의로는 요건을 충족하지 못합니다."
        ),
        "ref_doc": "kr-pipa-active-20251002",
        "tag": None,
        "priority": 760,
    },
    {
        "template_id": "act_reg_high_1",
        "scope": "SECTION",
        "trigger_type": "risk_level",
        "trigger_value": "높음",
        "action_text": "규제 위험도가 높음으로 산정됐습니다. 서비스 설명 전체에서 의료행위 암시 표현을 전수 점검하세요.",
        "ref_doc": None,
        "tag": None,
        "priority": 750,
    },
    {
        "template_id": "act_reg_mid_1",
        "scope": "SECTION",
        "trigger_type": "risk_level",
        "trigger_value": "중간",
        "action_text": "규제 위험도가 중간입니다. 교정 후보로 제시된 표현을 우선 검토·수정하세요.",
        "ref_doc": None,
        "tag": None,
        "priority": 740,
    },
    {
        "template_id": "act_reg_low_1",
        "scope": "SECTION",
        "trigger_type": "risk_level",
        "trigger_value": "낮음",
        "action_text": "규제 위험도가 낮습니다. 다만 예측·진단 등 기능이 추가되면 재판정이 필요할 수 있습니다.",
        "ref_doc": None,
        "tag": None,
        "priority": 710,
    },
]


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        for row in ROWS:
            existing = await session.get(ActionTemplate, row["template_id"])
            if existing is None:
                session.add(ActionTemplate(**row))
            else:
                for key, value in row.items():
                    if key != "template_id":
                        setattr(existing, key, value)
        await session.commit()

    print(f"action_templates(scope=SECTION) : {len(ROWS)}행")


if __name__ == "__main__":
    asyncio.run(seed())
