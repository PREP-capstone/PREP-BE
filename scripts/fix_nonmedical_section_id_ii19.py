from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.session import AsyncSessionLocal


DOCUMENT_ID = "kr-mohw-nonmedical-health-guide-202209"
OLD_SECTION_ID = "II.19"
NEW_SECTION_ID = "II.3"
EXPECTED_RISKY_TEXTS = ("진단 질환", "처방 질환", "치료 질환")


SELECT_TARGETS_SQL = text(
    """
    SELECT rule_id, risky_text, safe_text, legal_basis_article
    FROM correction_rules
    WHERE legal_basis_doc = :document_id
      AND legal_basis_article = :old_section_id
    ORDER BY risky_text
    """
)

UPDATE_EXPECTED_SQL = text(
    """
    UPDATE correction_rules
    SET legal_basis_article = :new_section_id
    WHERE legal_basis_doc = :document_id
      AND legal_basis_article = :old_section_id
      AND risky_text = ANY(:expected_risky_texts)
    RETURNING rule_id, risky_text, safe_text, legal_basis_article
    """
)


def is_expected_rule(row: dict[str, Any]) -> bool:
    return row["risky_text"] in EXPECTED_RISKY_TEXTS


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"Fix {DOCUMENT_ID} correction_rules section_id typo: {OLD_SECTION_ID} -> {NEW_SECTION_ID}."
    )
    parser.add_argument("--apply", action="store_true", help="Apply the UPDATE. Without this flag, dry-run only.")
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        before_rows = (
            await session.execute(
                SELECT_TARGETS_SQL,
                {"document_id": DOCUMENT_ID, "old_section_id": OLD_SECTION_ID},
            )
        ).mappings().all()

        expected_rows = [dict(row) for row in before_rows if is_expected_rule(dict(row))]
        unexpected_rows = [dict(row) for row in before_rows if not is_expected_rule(dict(row))]

        print(f"Found {len(before_rows)} correction_rules using {DOCUMENT_ID} {OLD_SECTION_ID}")
        print(f"Expected fix targets: {len(expected_rows)}")
        for row in expected_rows:
            print(f"- {row['rule_id']} {row['risky_text']} -> {NEW_SECTION_ID}")

        if unexpected_rows:
            print("Unexpected rows left untouched:")
            for row in unexpected_rows:
                print(f"- {row['rule_id']} {row['risky_text']} ({row['legal_basis_article']})")

        if not args.apply:
            print("Dry-run only. Re-run with --apply to update expected rows.")
            return

        updated_rows = (
            await session.execute(
                UPDATE_EXPECTED_SQL,
                {
                    "document_id": DOCUMENT_ID,
                    "old_section_id": OLD_SECTION_ID,
                    "new_section_id": NEW_SECTION_ID,
                    "expected_risky_texts": list(EXPECTED_RISKY_TEXTS),
                },
            )
        ).mappings().all()
        await session.commit()

        print(f"Updated correction_rules: {len(updated_rows)}")
        for row in updated_rows:
            print(f"- {row['rule_id']} {row['risky_text']} -> {row['legal_basis_article']}")


if __name__ == "__main__":
    asyncio.run(main())
