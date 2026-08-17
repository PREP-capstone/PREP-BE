from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.models.evidence_chunk import EvidenceChunk
from app.db.models.evidence_document import EvidenceDocument
from app.db.session import AsyncSessionLocal


DEFAULT_DOCUMENTS_CSV = ROOT / "data" / "rag" / "evidence_documents_draft.csv"
DEFAULT_CHUNKS_CSV = ROOT / "data" / "rag" / "evidence_chunks_draft.csv"


def parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"true", "1", "yes", "y"}


def parse_int(value: str | None) -> int | None:
    text = (value or "").strip()
    return int(text) if text else None


def parse_date(value: str | None) -> date | None:
    text = (value or "").strip()
    return date.fromisoformat(text) if text else None


def null_if_blank(value: str | None) -> str | None:
    text = clean_text(value)
    return text or None


def clean_text(value: str | None) -> str:
    return (value or "").replace("\x00", "").strip()


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def document_values(row: dict[str, str]) -> dict[str, Any]:
    return {
        "document_id": row["document_id"],
        "law_id": null_if_blank(row.get("law_id")),
        "title": clean_text(row["title"]),
        "doc_type": clean_text(row["doc_type"]),
        "source_subtype": null_if_blank(row.get("source_subtype")),
        "issuing_org": null_if_blank(row.get("issuing_org")),
        "jurisdiction": clean_text(row.get("jurisdiction")) or "KR",
        "rag_category": null_if_blank(row.get("rag_category")),
        "effective_date": parse_date(row.get("effective_date")),
        "publication_date": parse_date(row.get("publication_date")),
        "status": clean_text(row["status"]),
        "tag_regulatory": parse_bool(row.get("tag_regulatory")),
        "tag_privacy": parse_bool(row.get("tag_privacy")),
        "tag_advertising": parse_bool(row.get("tag_advertising")),
        "usage_scope": clean_text(row.get("usage_scope")) or "RAG",
        "source_url": null_if_blank(row.get("source_url")),
        "collection_source": null_if_blank(row.get("collection_source")),
        "processing_note": null_if_blank(row.get("processing_note")),
    }


def chunk_values(row: dict[str, str]) -> dict[str, Any]:
    return {
        "chunk_id": clean_text(row["chunk_id"]),
        "document_id": clean_text(row["document_id"]),
        "chunk_order": int(row["chunk_order"]),
        "section_id": null_if_blank(row.get("section_id")),
        "section_title": null_if_blank(row.get("section_title")),
        "chunk_type": clean_text(row["chunk_type"]),
        "chunk_text": clean_text(row["chunk_text"]),
        "page_start": parse_int(row.get("page_start")),
        "page_end": parse_int(row.get("page_end")),
        "char_count": parse_int(row.get("char_count")),
        "tag_regulatory": parse_bool(row.get("tag_regulatory")),
        "tag_privacy": parse_bool(row.get("tag_privacy")),
        "tag_advertising": parse_bool(row.get("tag_advertising")),
        "case_tag_advertising": parse_bool(row.get("case_tag_advertising")),
        "case_tag_privacy": parse_bool(row.get("case_tag_privacy")),
        "case_tag_medical_device": parse_bool(row.get("case_tag_medical_device")),
        "case_tag_health_functional_food": parse_bool(row.get("case_tag_health_functional_food")),
        "effective_date": parse_date(row.get("effective_date")),
        "status": clean_text(row["status"]),
        "source_url": null_if_blank(row.get("source_url")),
        "local_file_path": null_if_blank(row.get("local_file_path")),
    }


async def upsert_documents(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    async with AsyncSessionLocal() as session:
        stmt = insert(EvidenceDocument).values(rows)
        update_columns = {
            col.name: getattr(stmt.excluded, col.name)
            for col in EvidenceDocument.__table__.columns
            if col.name not in {"document_id", "created_at"}
        }
        await session.execute(stmt.on_conflict_do_update(
            index_elements=[EvidenceDocument.document_id],
            set_=update_columns,
        ))
        await session.commit()


async def upsert_chunks(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    async with AsyncSessionLocal() as session:
        stmt = insert(EvidenceChunk).values(rows)
        update_columns = {
            col.name: getattr(stmt.excluded, col.name)
            for col in EvidenceChunk.__table__.columns
            if col.name not in {"chunk_id", "created_at"}
        }
        await session.execute(stmt.on_conflict_do_update(
            index_elements=[EvidenceChunk.chunk_id],
            set_=update_columns,
        ))
        await session.commit()


async def delete_stale_chunks(rows: list[dict[str, Any]]) -> int:
    """Delete DB chunks for imported documents that are no longer present in the CSV."""

    if not rows:
        return 0

    document_ids = {row["document_id"] for row in rows}
    chunk_ids = {row["chunk_id"] for row in rows}

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(EvidenceChunk)
            .where(EvidenceChunk.document_id.in_(document_ids))
            .where(EvidenceChunk.chunk_id.not_in(chunk_ids))
        )
        await session.commit()
    return int(result.rowcount or 0)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Import RAG evidence CSV files into Postgres.")
    parser.add_argument("--documents-csv", type=Path, default=DEFAULT_DOCUMENTS_CSV)
    parser.add_argument("--chunks-csv", type=Path, default=DEFAULT_CHUNKS_CSV)
    parser.add_argument("--dry-run", action="store_true", help="Parse CSV files without DB writes.")
    parser.add_argument(
        "--sync-delete-stale-chunks",
        action="store_true",
        help="Delete existing DB chunks for imported documents when they are absent from the chunks CSV.",
    )
    args = parser.parse_args()

    document_rows = [document_values(row) for row in load_csv(args.documents_csv)]
    chunk_rows = [chunk_values(row) for row in load_csv(args.chunks_csv)]

    if args.dry_run:
        print(f"Parsed evidence_documents: {len(document_rows)}")
        print(f"Parsed evidence_chunks: {len(chunk_rows)}")
        return

    await upsert_documents(document_rows)
    await upsert_chunks(chunk_rows)
    deleted_chunks = 0
    if args.sync_delete_stale_chunks:
        deleted_chunks = await delete_stale_chunks(chunk_rows)

    print(f"Imported evidence_documents: {len(document_rows)}")
    print(f"Imported evidence_chunks: {len(chunk_rows)}")
    if args.sync_delete_stale_chunks:
        print(f"Deleted stale evidence_chunks: {deleted_chunks}")


if __name__ == "__main__":
    asyncio.run(main())
