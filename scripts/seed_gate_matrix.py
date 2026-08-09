"""gate_matrix 6칸 확정 시드데이터를 적재한다 (db_구축_설계서.md §3.2).

`GATE_MATRIX_TABLE`은 파이썬 상수일 뿐이라 DB에는 6행이 들어가 있지 않았다. 이 6건은
법령·고시 원문 근거를 100% 확보한 확정 조합이라 관리자 검수 없이 즉시 active로 적재할 수 있다.

verdict/priority는 `GATE_MATRIX_TABLE`에서 그대로 가져온다 — 상수와 DB가 갈라지지 않게 하기 위해
여기에 verdict를 다시 적어두지 않는다.

⚠️ 시드 적재 후에는 extract_B가 같은 조합을 다시 추출하면 auto_validate에서 "중복후보"로 걸린다.
6칸 표가 닫힌 확정 표가 된 이후 extract_b의 역할이 "신규 조합 탐지·기존 표 QA"로 좁혀졌으므로
(구현_현황_정리.md §Stage B) 의도된 동작이다.

    python scripts/seed_gate_matrix.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.models import GateMatrix, RuleVersion
from app.db.session import AsyncSessionLocal
from app.pipeline.article_ref import normalize_article
from app.pipeline.gate_matrix_table import GATE_MATRIX_TABLE, VERDICT_PRIORITY

WELLNESS = "kr-mfds-wellness-0091-03-20260212"  # 웰니스 판단기준 지침서-0091-03
LLM_GUIDE = "kr-mfds-llm-digital-medical-device-1511-01-20260630"  # LLM 기반 디지털의료기기 가이드라인

# (data_type, function_type) → 판정 근거. §3.2 매핑표의 "exemption_note / 근거" 열.
# article은 §1.5.1 표기 규칙(로마숫자 ASCII, 마침표 구분)을 따르며 RAG evidence_chunks.section_id와
# 조인되는 키다.
LEGAL_BASIS: dict[tuple[str, str], tuple[str, str]] = {
    ("생체지표", "단순기록"): (WELLNESS, "IV.1.가"),
    ("생체지표", "비교·추이분석"): (WELLNESS, "III.가"),
    ("생체지표", "수치예측·진단"): (WELLNESS, "IV.3"),
    ("라이프스타일", "단순기록"): (WELLNESS, "IV.1"),
    ("라이프스타일", "비교·추이분석"): (WELLNESS, "III.다"),
    ("라이프스타일", "수치예측·진단"): (LLM_GUIDE, "표3-1"),
}


async def _gate_matrix_rule_version(session) -> RuleVersion:
    """Stage B 전용 active rule_version을 확보한다 (publish.py의 Stage별 lineage와 동일 원리)."""
    existing = await session.scalar(
        select(RuleVersion)
        .join(GateMatrix, GateMatrix.rule_version_id == RuleVersion.rule_version_id)
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
        rule_version = await _gate_matrix_rule_version(session)
        inserted = 0

        for (data_type, function_type), lookup in GATE_MATRIX_TABLE.items():
            existing = await session.scalar(
                select(GateMatrix).where(
                    GateMatrix.rule_version_id == rule_version.rule_version_id,
                    GateMatrix.data_type == data_type,
                    GateMatrix.function_type == function_type,
                    GateMatrix.acquire_method.is_(None),
                )
            )
            if existing is not None:
                continue

            legal_basis_doc, legal_basis_article = LEGAL_BASIS[(data_type, function_type)]
            session.add(
                GateMatrix(
                    rule_version_id=rule_version.rule_version_id,
                    data_type=data_type,
                    function_type=function_type,
                    verdict=lookup["verdict"],
                    exemption_note=lookup["exemption_note"],
                    # 6칸 기본 조합은 침습적 하드체크 대상이 아니므로 acquire_method를 비워둔다 (§3.2).
                    acquire_method=None,
                    # TODO(D-2): avoidance_* 문구 작성 주체 미정 — FAIL row도 아직 비워둔다.
                    avoidance_redesign=None,
                    avoidance_certification=None,
                    legal_basis_doc=legal_basis_doc,
                    legal_basis_article=normalize_article(legal_basis_article),
                    risk_code=None,
                    priority=VERDICT_PRIORITY[lookup["verdict"]],
                )
            )
            inserted += 1

        await session.commit()
        print(f"gate_matrix: {inserted}행 신규 적재 (rule_version={rule_version.version}, 총 6칸)")


if __name__ == "__main__":
    asyncio.run(seed())
