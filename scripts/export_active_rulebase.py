"""룰베이스 active 데이터를 배포용 SQL INSERT 덤프 + 테이블별 CSV로 내보낸다.

새 환경(스테이징, 팀원 로컬, 신규 RDS 등)을 세팅할 때 LLM 파이프라인을 처음부터
다시 돌리지 않고 이 파일 하나로 바로 seed할 수 있게 하기 위한 스크립트다.

대상: rule_versions.status='active'인 최신 계보(gate_keywords/gate_matrix/
correction_rules/signal_config) + 버전 무관 참조 테이블 전체
(data_difficulty/collection_difficulty/verb_substitution).

출력 SQL은 BEGIN/COMMIT으로 감싸여 있어 대상 DB에 그대로 실행 가능하다. 단,
대상 DB의 해당 테이블이 이미 채워져 있으면 PK/UNIQUE 충돌이 날 수 있으므로
"빈 DB에 최초 적재" 또는 "완전히 비우고 재적재"를 전제로 한다.

    python scripts/export_active_rulebase.py
    python scripts/export_active_rulebase.py --sql-out data/rule/rulebase_active_export.sql --csv-dir data/rule/csv_export
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.db.models import (
    CollectionDifficulty,
    CorrectionRule,
    DataDifficulty,
    GateKeyword,
    GateMatrix,
    RuleVersion,
    SignalConfig,
    VerbSubstitution,
)
from app.db.session import AsyncSessionLocal

DEFAULT_SQL_OUT = ROOT / "data" / "rule" / "rulebase_active_export.sql"
DEFAULT_CSV_DIR = ROOT / "data" / "rule" / "csv_export"

# (모델, 결과 파일 라벨, 버전 스코프 여부) — 버전 스코프인 것만 status='active' 필터를 건다.
_VERSIONED_TABLES = [
    (GateKeyword, "gate_keywords"),
    (GateMatrix, "gate_matrix"),
    (CorrectionRule, "correction_rules"),
    (SignalConfig, "signal_config"),
]
_REFERENCE_TABLES = [
    (DataDifficulty, "data_difficulty"),
    (CollectionDifficulty, "collection_difficulty"),
    (VerbSubstitution, "verb_substitution"),
]


def _insert_sql(row) -> str:
    """SQLAlchemy 컴파일러로 literal-binds INSERT문을 만든다.

    수기로 따옴표를 이스케이프하지 않고 dialect의 literal processor에 맡겨야
    문자열 안의 작은따옴표·NULL·UUID·datetime 등이 안전하게 처리된다.
    """
    model = type(row)
    values = {c.name: getattr(row, c.name) for c in model.__table__.columns}
    stmt = model.__table__.insert().values(**values)
    compiled = stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    return str(compiled) + ";"


async def _active_rows(session, model):
    result = await session.execute(
        select(model)
        .join(RuleVersion, RuleVersion.rule_version_id == model.rule_version_id)
        .where(RuleVersion.status == "active")
    )
    return list(result.scalars().all())


async def _all_rows(session, model, order_by=None):
    stmt = select(model)
    if order_by is not None:
        stmt = stmt.order_by(order_by)
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _write_csv(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    columns = [c.name for c in type(rows[0]).__table__.columns]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([getattr(row, c) for c in columns])


async def export(sql_out: Path, csv_dir: Path | None) -> None:
    async with AsyncSessionLocal() as session:
        # 활성 rule_version만 추린다 (gate_keywords/gate_matrix/correction_rules/signal_config가
        # 실제로 참조하는 것만 — 고아 버전이 섞이지 않도록 각 테이블에서 쓰는 rule_version_id만 모은다).
        versioned_rows: dict[str, list] = {}
        used_version_ids: set = set()
        for model, label in _VERSIONED_TABLES:
            rows = await _active_rows(session, model)
            versioned_rows[label] = rows
            used_version_ids.update(row.rule_version_id for row in rows)

        rule_versions = [
            v
            for v in await _all_rows(session, RuleVersion)
            if v.rule_version_id in used_version_ids
        ]

        reference_rows: dict[str, list] = {}
        for model, label in _REFERENCE_TABLES:
            reference_rows[label] = await _all_rows(session, model)

    # ---- SQL 덤프 ----
    lines = [
        "-- PREP-BE 룰베이스 active 데이터 배포용 SQL INSERT 덤프",
        f"-- 생성: {datetime.now(timezone.utc).strftime('%Y-%m-%d')} "
        "(scripts/export_active_rulebase.py 로 재생성 가능 — 재생성 시 이 파일을 덮어쓸 것)",
        "-- 대상: rule_versions.status='active' 최신 계보(gate_keywords/gate_matrix/"
        "correction_rules/signal_config) + 참조 테이블 전체(data_difficulty/"
        "collection_difficulty/verb_substitution)",
        "BEGIN;",
        "SET CONSTRAINTS ALL DEFERRED;",
        "",
        "-- rule_versions",
    ]
    for row in rule_versions:
        lines.append(_insert_sql(row))
    lines.append("")

    for _, label in _VERSIONED_TABLES:
        lines.append(f"-- {label}")
        for row in versioned_rows[label]:
            lines.append(_insert_sql(row))
        lines.append("")

    for _, label in _REFERENCE_TABLES:
        lines.append(f"-- {label}")
        for row in reference_rows[label]:
            lines.append(_insert_sql(row))
        lines.append("")

    lines.append("COMMIT;")

    sql_out.parent.mkdir(parents=True, exist_ok=True)
    sql_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"SQL 덤프: {sql_out}")

    # ---- CSV ----
    if csv_dir is not None:
        _write_csv(csv_dir / "rule_versions.csv", rule_versions)
        for _, label in _VERSIONED_TABLES:
            _write_csv(csv_dir / f"{label}.csv", versioned_rows[label])
        for _, label in _REFERENCE_TABLES:
            _write_csv(csv_dir / f"{label}.csv", reference_rows[label])
        print(f"CSV: {csv_dir}/")

    # ---- 요약 ----
    print("\n행 수 요약")
    print(f"  rule_versions        {len(rule_versions)}")
    for _, label in _VERSIONED_TABLES:
        print(f"  {label:<20} {len(versioned_rows[label])}")
    for _, label in _REFERENCE_TABLES:
        print(f"  {label:<20} {len(reference_rows[label])}")


def main() -> None:
    parser = argparse.ArgumentParser(description="룰베이스 active 데이터를 SQL/CSV로 내보낸다.")
    parser.add_argument("--sql-out", default=str(DEFAULT_SQL_OUT), help="SQL 덤프 출력 경로")
    parser.add_argument("--csv-dir", default=str(DEFAULT_CSV_DIR), help="CSV 출력 디렉토리 (빈 문자열이면 CSV 생략)")
    args = parser.parse_args()

    csv_dir = Path(args.csv_dir) if args.csv_dir else None
    asyncio.run(export(Path(args.sql_out), csv_dir))


if __name__ == "__main__":
    main()
