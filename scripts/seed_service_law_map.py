"""service_law_map 1차 시드. 판정엔진_개발설계서.md §15.2.

service_type 4종(앱단독/웨어러블연동/기기연동/오프라인결합) × 적용 법령. applicable_laws는
evidence_documents.document_id를 참조하므로 실제 시드된 문서 ID만 사용한다(2026-08-23,
evidence_documents 전체 조회로 확인).

⚠️ service_type 값이 competitors·세션 입력폼의 service_type과 완전히 같은 문자열이어야
매칭된다 — 프론트/2번과 표기 통일 필요.

재실행해도 안전하다(있으면 갱신, 없으면 삽입).

    python scripts/seed_service_law_map.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.models import ServiceLawMap
from app.db.session import AsyncSessionLocal

ROWS = [
    {
        "service_type": "앱단독",
        "applicable_laws": [
            "kr-mfds-wellness-0091-03-20260212",
            "kr-mohw-nonmedical-health-guide-202209",
            "kr-pipa-active-20251002",
        ],
        "description": (
            "소프트웨어 단독 서비스 — 웰니스 판단기준·비의료 건강관리서비스 가이드라인으로 "
            "의료기기 해당 여부를 먼저 판단하고, 개인정보 처리 전반은 개인정보 보호법을 적용한다."
        ),
    },
    {
        "service_type": "웨어러블연동",
        "applicable_laws": [
            "kr-mfds-wellness-0091-03-20260212",
            "kr-mfds-mobile-medical-app-guide-20200225",
            "kr-medical-device-act-20260701",
            "kr-pipa-active-20251002",
        ],
        "description": (
            "웨어러블 기기와 OS 레이어(HealthKit·Health Connect 등)로 연동하는 서비스 — "
            "모바일 의료용 앱 안전관리 지침과 의료기기법상 의료기기 해당 여부를 함께 검토한다."
        ),
    },
    {
        "service_type": "기기연동",
        "applicable_laws": [
            "kr-medical-device-act-20260701",
            "kr-medical-device-act-rule-20260701",
            "kr-mfds-wellness-0091-03-20260212",
            "kr-pipa-active-20251002",
        ],
        "description": (
            "제조사 기기·API와 직접 통신하는 서비스 — 침습적 하드체크(웰니스 판단기준)와 "
            "의료기기법·시행규칙 적용 가능성이 4종 중 가장 높다."
        ),
    },
    {
        "service_type": "오프라인결합",
        "applicable_laws": [
            "kr-medical-act-20260407",
            "kr-pharmaceutical-affairs-act-20260621",
            "kr-pipa-active-20251002",
        ],
        "description": (
            "오프라인 의료·약무 행위와 결합된 서비스 — 의료법상 의료행위 해당 여부, "
            "복약지도 등은 약사법 적용 대상인지 함께 검토한다."
        ),
    },
]


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        for row in ROWS:
            existing = await session.get(ServiceLawMap, row["service_type"])
            if existing is None:
                session.add(ServiceLawMap(**row))
            else:
                existing.applicable_laws = row["applicable_laws"]
                existing.description = row["description"]
        await session.commit()

    print(f"service_law_map : {len(ROWS)}행")


if __name__ == "__main__":
    asyncio.run(seed())
