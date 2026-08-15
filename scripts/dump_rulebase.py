"""룰베이스 DB에 무엇이 들어갔는지 사람이 읽을 수 있게 출력한다.

    python scripts/dump_rulebase.py [--stage A] [--max-width 40] [--out PATH]

건수가 적으므로 전량 출력한다. rule_versions는 Stage별 active 계보를 함께 보여준다.

출력은 화면과 파일에 **동시에** 쓰고 매 줄 flush한다. 터미널 출력이 잘리거나 중간에
끊겨도 파일로 전량을 확인할 수 있어야 하기 때문이다(기본 경로: data/rule/dump_latest.txt).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select

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
)
from app.db.session import AsyncSessionLocal

_STAGE_MODEL = {"A": GateKeyword, "B": GateMatrix, "C": CorrectionRule}
DEFAULT_OUT = ROOT / "data" / "rule" / "dump_latest.txt"

_out_file = None


def emit(line: str = "") -> None:
    """화면과 파일에 동시에 쓰고 즉시 flush한다 (중단돼도 여기까지는 남는다)."""
    print(line, flush=True)
    if _out_file is not None:
        _out_file.write(line + "\n")
        _out_file.flush()


def _cell(value, max_width: int) -> str:
    if value is None:
        return "-"
    text = str(value).replace("\n", " ").strip()
    return text if len(text) <= max_width else text[: max_width - 1] + "…"


def print_table(title: str, headers: list[str], rows: list[list], max_width: int) -> None:
    emit(f"\n### {title}  ({len(rows)}행)")
    if not rows:
        emit("  (비어 있음)")
        return

    cells = [[_cell(v, max_width) for v in row] for row in rows]
    widths = [
        max(len(headers[i]), max((len(r[i]) for r in cells), default=0))
        for i in range(len(headers))
    ]
    line = "  " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    emit(line)
    emit("  " + "-+-".join("-" * w for w in widths))
    for row in cells:
        emit("  " + " | ".join(row[i].ljust(widths[i]) for i in range(len(headers))))


def print_distribution(title: str, pairs: list[tuple]) -> None:
    emit(f"\n  [{title}]")
    if not pairs:
        emit("    (없음)")
        return
    for value, count in pairs:
        emit(f"    {value if value is not None else '-'}: {count}")


async def dump(stage_filter: str | None, max_width: int) -> None:
    async with AsyncSessionLocal() as session:
        # ---- 요약 ----
        emit("=" * 70)
        emit("룰베이스 DB 덤프")
        emit("=" * 70)
        emit("\n### 테이블별 행 수")
        for label, model, pk in [
            ("rule_versions", RuleVersion, RuleVersion.rule_version_id),
            ("gate_keywords", GateKeyword, GateKeyword.keyword_id),
            ("gate_matrix", GateMatrix, GateMatrix.matrix_id),
            ("correction_rules", CorrectionRule, CorrectionRule.rule_id),
            ("signal_config", SignalConfig, SignalConfig.config_id),
            ("data_difficulty", DataDifficulty, DataDifficulty.data_type),
            ("collection_difficulty", CollectionDifficulty, CollectionDifficulty.method),
        ]:
            count = await session.scalar(select(func.count()).select_from(model))
            emit(f"  {label:<24} {count}")

        # ---- rule_versions (Stage별 active 계보) ----
        versions = (
            await session.execute(
                select(RuleVersion).order_by(RuleVersion.created_at, RuleVersion.version)
            )
        ).scalars().all()

        owners: dict[str, list[str]] = {}
        for stage, model in _STAGE_MODEL.items():
            for version_id in (
                await session.scalars(select(model.rule_version_id).distinct())
            ).all():
                owners.setdefault(str(version_id), []).append(stage)
        for version_id in (await session.scalars(select(SignalConfig.rule_version_id).distinct())).all():
            owners.setdefault(str(version_id), []).append("signal_config")

        print_table(
            "rule_versions",
            ["version", "status", "보유 데이터", "rule_version_id"],
            [
                [
                    v.version,
                    v.status,
                    ",".join(owners.get(str(v.rule_version_id), [])) or "(없음)",
                    str(v.rule_version_id),
                ]
                for v in versions
            ],
            max_width,
        )

        active_by_stage = {
            stage: [
                v.version
                for v in versions
                if v.status == "active" and stage in owners.get(str(v.rule_version_id), [])
            ]
            for stage in _STAGE_MODEL
        }
        emit("\n  [Stage별 active 버전]")
        for stage, active in active_by_stage.items():
            table = {"A": "gate_keywords", "B": "gate_matrix", "C": "correction_rules"}[stage]
            note = "" if len(active) <= 1 else "  ⚠️ active가 2개 이상입니다"
            emit(f"    Stage {stage} ({table}): {', '.join(active) or '(없음)'}{note}")

        # ---- gate_keywords ----
        if stage_filter in (None, "A"):
            rows = (
                await session.execute(
                    select(GateKeyword, RuleVersion.version, RuleVersion.status)
                    .join(RuleVersion, RuleVersion.rule_version_id == GateKeyword.rule_version_id)
                    .order_by(RuleVersion.status, GateKeyword.keyword)
                )
            ).all()
            print_table(
                "gate_keywords (Stage A)",
                ["keyword", "type", "category", "focus", "verdict", "w", "ver", "status"],
                [
                    [r.keyword, r.type, r.keyword_category, r.data_type_focus, r.verdict, r.weight,
                     version, status]
                    for r, version, status in rows
                ],
                max_width,
            )
            for label, column in [
                ("type 분포", GateKeyword.type),
                ("keyword_category 분포", GateKeyword.keyword_category),
                ("verdict 분포", GateKeyword.verdict),
                ("weight 분포", GateKeyword.weight),
            ]:
                pairs = (
                    await session.execute(
                        select(column, func.count())
                        .join(RuleVersion, RuleVersion.rule_version_id == GateKeyword.rule_version_id)
                        .where(RuleVersion.status == "active")
                        .group_by(column)
                        .order_by(column)
                    )
                ).all()
                print_distribution(f"{label} (active만)", [(p[0], p[1]) for p in pairs])

        # ---- gate_matrix ----
        if stage_filter in (None, "B"):
            rows = (
                await session.execute(
                    select(GateMatrix, RuleVersion.version, RuleVersion.status)
                    .join(RuleVersion, RuleVersion.rule_version_id == GateMatrix.rule_version_id)
                    .order_by(RuleVersion.status, GateMatrix.data_type, GateMatrix.function_type)
                )
            ).all()
            print_table(
                "gate_matrix (Stage B)",
                [
                    "data_type",
                    "function_type",
                    "verdict",
                    "pri",
                    "acquire",
                    "legal_basis_doc",
                    "article",
                    "ver",
                    "status",
                ],
                [
                    [
                        r.data_type,
                        r.function_type,
                        r.verdict,
                        r.priority,
                        r.acquire_method,
                        r.legal_basis_doc,
                        r.legal_basis_article,
                        version,
                        status,
                    ]
                    for r, version, status in rows
                ],
                max_width,
            )

        # ---- correction_rules ----
        if stage_filter in (None, "C"):
            rows = (
                await session.execute(
                    select(CorrectionRule, RuleVersion.version, RuleVersion.status)
                    .join(RuleVersion, RuleVersion.rule_version_id == CorrectionRule.rule_version_id)
                    .order_by(RuleVersion.status, CorrectionRule.risky_text)
                )
            ).all()
            print_table(
                "correction_rules (Stage C)",
                ["risky_text", "safe_text", "reg", "adv", "legal_basis_doc", "article", "ver", "status"],
                [
                    [
                        r.risky_text,
                        r.safe_text,
                        r.regulatory_score,
                        r.advertising_score,
                        r.legal_basis_doc,
                        r.legal_basis_article,
                        version,
                        status,
                    ]
                    for r, version, status in rows
                ],
                max_width,
            )
            for label, column in [
                ("regulatory_score 분포", CorrectionRule.regulatory_score),
                ("advertising_score 분포", CorrectionRule.advertising_score),
            ]:
                pairs = (
                    await session.execute(
                        select(column, func.count())
                        .join(RuleVersion, RuleVersion.rule_version_id == CorrectionRule.rule_version_id)
                        .where(RuleVersion.status == "active")
                        .group_by(column)
                        .order_by(column)
                    )
                ).all()
                print_distribution(f"{label} (active만)", [(p[0], p[1]) for p in pairs])

        emit()


def main() -> None:
    parser = argparse.ArgumentParser(description="룰베이스 DB 내용을 출력한다.")
    parser.add_argument("--stage", choices=["A", "B", "C"], help="특정 Stage 테이블만 출력")
    parser.add_argument("--max-width", type=int, default=40, help="셀 최대 폭 (기본 40)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="덤프 파일 경로 (빈 문자열이면 파일 미기록)")
    args = parser.parse_args()

    global _out_file
    out_path = Path(args.out) if args.out else None
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _out_file = out_path.open("w", encoding="utf-8")
    try:
        asyncio.run(dump(args.stage, args.max_width))
    finally:
        if _out_file:
            _out_file.close()
            print(f"\n덤프 파일: {out_path}", flush=True)


if __name__ == "__main__":
    main()
