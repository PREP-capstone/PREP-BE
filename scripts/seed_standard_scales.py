from __future__ import annotations

import asyncio
import argparse
import sys
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.models import StandardScale
from app.db.session import AsyncSessionLocal


STANDARD_SCALES = [
    {
        "scale_id": "scale_phq_9",
        "name": "PHQ-9",
        "full_name": "Patient Health Questionnaire-9",
        "category_1": "정신건강",
        "item_count": 9,
        "scoring_range": "0-27",
        "license_type": "사용 조건 확인 필요",
        "source_url": "https://www.phqscreeners.com/",
        "note": "우울 증상 자가보고 선별에 널리 쓰이는 표준 척도 후보입니다.",
    },
    {
        "scale_id": "scale_gad_7",
        "name": "GAD-7",
        "full_name": "Generalized Anxiety Disorder-7",
        "category_1": "정신건강",
        "item_count": 7,
        "scoring_range": "0-21",
        "license_type": "사용 조건 확인 필요",
        "source_url": "https://www.phqscreeners.com/",
        "note": "불안 증상 자가보고 선별에 널리 쓰이는 표준 척도 후보입니다.",
    },
    {
        "scale_id": "scale_pss_10",
        "name": "PSS-10",
        "full_name": "Perceived Stress Scale-10",
        "category_1": "정신건강",
        "item_count": 10,
        "scoring_range": "0-40",
        "license_type": "사용 조건 확인 필요",
        "source_url": "https://www.cmu.edu/dietrich/psychology/stress-immunity-disease-lab/scales/index.html",
        "note": "인지된 스트레스 수준을 자가보고로 측정하는 척도 후보입니다.",
    },
    {
        "scale_id": "scale_isi",
        "name": "ISI",
        "full_name": "Insomnia Severity Index",
        "category_1": "수면",
        "item_count": 7,
        "scoring_range": "0-28",
        "license_type": "사용 조건 확인 필요",
        "source_url": "https://www.myhealth.va.gov/mhv-portal-web/insomnia-severity-index",
        "note": "불면 심각도를 자가보고로 확인할 때 활용 가능한 척도 후보입니다.",
    },
    {
        "scale_id": "scale_psqi",
        "name": "PSQI",
        "full_name": "Pittsburgh Sleep Quality Index",
        "category_1": "수면",
        "item_count": 19,
        "scoring_range": "0-21",
        "license_type": "라이선스 확인 필요",
        "source_url": "https://www.sleep.pitt.edu/instruments/",
        "note": "수면의 질 평가에 쓰이는 척도이나 사용 허가 조건 확인이 필요합니다.",
    },
    {
        "scale_id": "scale_ipaq_sf",
        "name": "IPAQ-SF",
        "full_name": "International Physical Activity Questionnaire Short Form",
        "category_1": "운동",
        "item_count": 7,
        "scoring_range": "MET-min/week",
        "license_type": "사용 조건 확인 필요",
        "source_url": "https://sites.google.com/view/ipaq",
        "note": "신체활동량 자가보고 대체 근거로 활용 가능한 척도 후보입니다.",
    },
    {
        "scale_id": "scale_eq_5d_5l",
        "name": "EQ-5D-5L",
        "full_name": "EuroQol 5-Dimension 5-Level",
        "category_1": "만성질환관리",
        "item_count": 5,
        "scoring_range": "5 dimensions + VAS",
        "license_type": "라이선스 확인 필요",
        "source_url": "https://euroqol.org/eq-5d-instruments/eq-5d-5l-about/",
        "note": "건강 관련 삶의 질 측정 척도이나 라이선스 확인이 필요합니다.",
    },
    {
        "scale_id": "scale_who_5",
        "name": "WHO-5",
        "full_name": "WHO-5 Well-Being Index",
        "category_1": "정신건강",
        "item_count": 5,
        "scoring_range": "0-25",
        "license_type": "사용 조건 확인 필요",
        "source_url": "https://www.psykiatri-regionh.dk/who-5/Pages/default.aspx",
        "note": "주관적 웰빙을 간단히 자가보고로 측정하는 척도 후보입니다.",
    },
    {
        "scale_id": "scale_bfi_10",
        "name": "BFI-10",
        "full_name": "Big Five Inventory-10",
        "category_1": "정신건강",
        "item_count": 10,
        "scoring_range": "성격 5요인",
        "license_type": "사용 조건 확인 필요",
        "source_url": "https://www.gesis.org/en/services/planning-studies-and-collecting-data/items-scales/bfi-10",
        "note": "멘탈/라이프스타일 서비스에서 성향 기반 입력을 대체할 때 검토 가능한 척도 후보입니다.",
    },
    {
        "scale_id": "scale_pregnancy_risk_checklist",
        "name": "임신 건강 체크리스트",
        "full_name": "Pregnancy Health Self-Report Checklist",
        "category_1": "여성건강",
        "item_count": None,
        "scoring_range": None,
        "license_type": "서비스별 문항 설계 필요",
        "source_url": None,
        "note": "임산부 상태 모니터링은 진단 표현을 피하고 자가보고 체크리스트 수준으로 설계해야 합니다.",
    },
]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed standard_scales reference rows.")
    parser.add_argument("--dry-run", action="store_true", help="Print row count without DB writes.")
    args = parser.parse_args()

    if args.dry_run:
        print(f"standard_scales: {len(STANDARD_SCALES)}")
        return

    stmt = insert(StandardScale).values(STANDARD_SCALES)
    update_columns = {
        column.name: getattr(stmt.excluded, column.name)
        for column in StandardScale.__table__.columns
        if column.name not in {"scale_id", "created_at"}
    }

    async with AsyncSessionLocal() as session:
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[StandardScale.scale_id],
                set_=update_columns,
            )
        )
        await session.commit()

    print(f"Seeded standard_scales: {len(STANDARD_SCALES)}")


if __name__ == "__main__":
    asyncio.run(main())
