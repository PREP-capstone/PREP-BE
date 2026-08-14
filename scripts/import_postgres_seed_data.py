from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from sqlalchemy.dialects.postgresql import insert

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.models.catalog import (
    ActionTemplate,
    ApiCatalog,
    BmMapping,
    Competitor,
    DataSensitivity,
    MvpStrategyTemplate,
    PublicDataCatalog,
    TrendSignalConfig,
)
from app.db.session import AsyncSessionLocal


DEFAULT_DATA_DIR = ROOT / "data" / "postgres"
NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def clean_text(value: Any) -> str:
    return str(value or "").replace("\x00", "").strip()


def null_if_blank(value: Any) -> str | None:
    text = clean_text(value)
    return text or None


def parse_int(value: Any) -> int | None:
    text = clean_text(value)
    if not text:
        return None
    return int(float(text))


def parse_bool(value: Any) -> bool:
    text = clean_text(value).lower()
    return text in {"1", "1.0", "true", "y", "yes", "예", "필요"}


def parse_date(value: Any) -> date | None:
    text = clean_text(value)
    if not text:
        return None

    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass

    try:
        serial = float(text)
    except ValueError:
        return None

    # Excel stores dates as days from 1899-12-30 in the common 1900 date system.
    return date(1899, 12, 30) + timedelta(days=int(serial))


def column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    value = 0
    for ch in letters:
        value = value * 26 + ord(ch.upper()) - 64
    return value - 1


def shared_strings(zip_file: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zip_file.namelist():
        return []

    root = ET.fromstring(zip_file.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.findall("a:si", NS):
        strings.append("".join(t.text or "" for t in item.findall(".//a:t", NS)))
    return strings


def workbook_sheets(zip_file: ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(zip_file.read("xl/workbook.xml"))
    relationships = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
    targets = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in relationships.findall(f"{{{REL_NS}}}Relationship")
    }

    sheets: dict[str, str] = {}
    for sheet in workbook.findall("a:sheets/a:sheet", NS):
        rel_id = sheet.attrib[f"{{{NS['r']}}}id"]
        target = targets[rel_id]
        if not target.startswith("xl/"):
            target = "xl/" + target.lstrip("/")
        sheets[sheet.attrib["name"]] = target
    return sheets


def load_sheet(path: Path, sheet_name: str) -> list[list[str]]:
    with ZipFile(path) as zip_file:
        strings = shared_strings(zip_file)
        target = workbook_sheets(zip_file)[sheet_name]
        root = ET.fromstring(zip_file.read(target))

        rows: list[list[str]] = []
        for row in root.findall(".//a:sheetData/a:row", NS):
            values: list[str] = []
            for cell in row.findall("a:c", NS):
                index = column_index(cell.attrib.get("r", "A"))
                while len(values) <= index:
                    values.append("")

                raw_value = cell.find("a:v", NS)
                if raw_value is None:
                    value = ""
                elif cell.attrib.get("t") == "s":
                    value = strings[int(raw_value.text or "0")]
                else:
                    value = raw_value.text or ""
                values[index] = value
            rows.append(values)
        return rows


def dict_rows(
    path: Path,
    sheet_name: str,
    *,
    header_row_index: int = 0,
    max_columns: int | None = None,
) -> list[dict[str, str]]:
    rows = load_sheet(path, sheet_name)
    header = rows[header_row_index]
    if max_columns is not None:
        header = header[:max_columns]

    output: list[dict[str, str]] = []
    for row in rows[header_row_index + 1 :]:
        if max_columns is not None:
            row = row[:max_columns]
        values = {header[index]: row[index] if index < len(row) else "" for index in range(len(header))}
        output.append(values)
    return output


def load_data_sensitivity(data_dir: Path) -> list[dict[str, Any]]:
    rows = dict_rows(data_dir / "data_sensitivity.xlsx", "data_sensitivity", max_columns=8)
    return [
        {
            "item_code": clean_text(row["item_code"]),
            "item_label": clean_text(row["item_label"]),
            "data_type": clean_text(row["data_type"]),
            "sensitivity_level": parse_int(row["sensitivity_level"]) or 0,
            "requires_separate_consent": parse_bool(row["requires_separate_consent"]),
            "legal_basis_doc": null_if_blank(row["legal_basis_doc"]),
            "legal_basis_article": null_if_blank(row["legal_basis_article"]),
            "note": null_if_blank(row["note"]),
        }
        for row in rows
        if clean_text(row.get("item_code"))
    ]


def load_public_data_catalog(data_dir: Path) -> list[dict[str, Any]]:
    rows = dict_rows(data_dir / "public_data_catalog.xlsx", "public_data_catalog.csv")
    return [
        {
            "dataset_id": clean_text(row["dataset_id"]),
            "name": clean_text(row["name"]),
            "org": null_if_blank(row["org"]),
            "url": null_if_blank(row["url"]),
            "category_1_tags": null_if_blank(row["category_1_tags"]),
            "data_type": null_if_blank(row["data_type"]),
            "access_type": null_if_blank(row["access_type"]),
            "difficulty": parse_int(row["difficulty"]),
            "update_cycle": null_if_blank(row["update_cycle"]),
            "note": null_if_blank(row["note"]),
        }
        for row in rows
        if clean_text(row.get("dataset_id"))
    ]


def load_api_catalog(data_dir: Path) -> list[dict[str, Any]]:
    rows = dict_rows(data_dir / "Api_catalog_and_Trend.xlsx", "api_catalog")
    return [
        {
            "api_id": clean_text(row["api_id"]),
            "name": clean_text(row["name"]),
            "provider": null_if_blank(row["provider"]),
            "url": null_if_blank(row["url"]),
            "available_data_types": null_if_blank(row["available_data_types"]),
            "platform": null_if_blank(row["platform"]),
            "access_type": null_if_blank(row["access_type"]),
            "integration_difficulty": parse_int(row["integration_difficulty"]),
            "collection_method": null_if_blank(row["collection_method_S축"]),
            "note": null_if_blank(row["note"]),
        }
        for row in rows
        if clean_text(row.get("api_id")).startswith("api_")
    ]


def load_trend_signal_config(data_dir: Path) -> list[dict[str, Any]]:
    rows = dict_rows(
        data_dir / "Api_catalog_and_Trend.xlsx",
        "signal_config_저장형식",
        header_row_index=2,
    )
    return [
        {
            "axis_key": clean_text(row["axis_key"]),
            "value": clean_text(row["value"]),
            "unit": null_if_blank(row["unit"]),
            "note": null_if_blank(row["note"]),
        }
        for row in rows
        if clean_text(row.get("axis_key")).startswith("trend_")
    ]


def load_action_templates(data_dir: Path) -> list[dict[str, Any]]:
    rows = dict_rows(data_dir / "action_templates.xlsx", "시트1")
    return [
        {
            "template_id": clean_text(row["template_id"]),
            "scope": clean_text(row["scope"]),
            "trigger_type": clean_text(row["trigger_type"]),
            "trigger_value": clean_text(row["trigger_value"]),
            "action_text": clean_text(row["action_text"]),
            "ref_doc": null_if_blank(row["ref_doc"]),
            "tag": null_if_blank(row["tag"]),
            "priority": parse_int(row["priority"]) or 0,
        }
        for row in rows
        if clean_text(row.get("template_id"))
    ]


def load_mvp_strategy_templates(data_dir: Path) -> list[dict[str, Any]]:
    rows = dict_rows(data_dir / "mvp_strategy_tempates.xlsx", "시트1")
    return [
        {
            "template_id": clean_text(row["template_id"]),
            "category_1": null_if_blank(row["category_1"]),
            "difficulty_level": clean_text(row["difficulty_level"]),
            "stage": parse_int(row["stage"]) or 0,
            "title": clean_text(row["title"]),
            "description": clean_text(row["description"]),
        }
        for row in rows
        if clean_text(row.get("template_id"))
    ]


def load_competitors(data_dir: Path) -> list[dict[str, Any]]:
    rows = load_sheet(data_dir / "경쟁사DB_BM매핑_수집시트.xlsx", "competitors")
    output: list[dict[str, Any]] = []
    for row in rows[1:]:
        competitor_id = clean_text(row[0] if len(row) > 0 else "")
        if not competitor_id:
            continue
        output.append(
            {
                "competitor_id": competitor_id,
                "name": clean_text(row[1] if len(row) > 1 else ""),
                "category_1": null_if_blank(row[2] if len(row) > 2 else ""),
                "category_2": null_if_blank(row[3] if len(row) > 3 else ""),
                "country": null_if_blank(row[4] if len(row) > 4 else ""),
                "tier": null_if_blank(row[5] if len(row) > 5 else ""),
                "data_type": null_if_blank(row[6] if len(row) > 6 else ""),
                "target": null_if_blank(row[7] if len(row) > 7 else ""),
                "service_type": null_if_blank(row[8] if len(row) > 8 else ""),
                "core_tags": null_if_blank(row[9] if len(row) > 9 else ""),
                "sub_tags": null_if_blank(row[10] if len(row) > 10 else ""),
                "bm_pattern": null_if_blank(row[11] if len(row) > 11 else ""),
                "note": null_if_blank(row[12] if len(row) > 12 else ""),
                "source_created_at": parse_date(row[13] if len(row) > 13 else ""),
                "source_updated_at": parse_date(row[14] if len(row) > 14 else ""),
                "limitation": null_if_blank(row[18] if len(row) > 18 else ""),
                "price": null_if_blank(row[19] if len(row) > 19 else ""),
            }
        )
    return output


def load_bm_mapping(data_dir: Path) -> list[dict[str, Any]]:
    rows = dict_rows(data_dir / "경쟁사DB_BM매핑_수집시트.xlsx", "bm_mapping")
    return [
        {
            "mapping_id": clean_text(row["mapping_id"]),
            "category_1": null_if_blank(row["category_1"]),
            "category_2": null_if_blank(row["category_2"]),
            "target": null_if_blank(row["target"]),
            "service_type": null_if_blank(row["service_type"]),
            "bm_pattern": null_if_blank(row["bm_pattern"]),
            "frequency_score": parse_int(row["frequency_score"]),
            "frequency_score_global": parse_int(row["frequency_score_global"]),
            "precedent_level": null_if_blank(row["precedent_level"]),
            "contributing_competitor_ids": null_if_blank(row["contributing_competitor_ids"]),
            "evidence_id": null_if_blank(row["evidence_id"]),
            "last_computed_at": parse_date(row["last_computed_at"]),
        }
        for row in rows
        if clean_text(row.get("mapping_id"))
    ]


def load_all(data_dir: Path) -> list[tuple[type[Any], list[dict[str, Any]]]]:
    return [
        (DataSensitivity, load_data_sensitivity(data_dir)),
        (PublicDataCatalog, load_public_data_catalog(data_dir)),
        (ApiCatalog, load_api_catalog(data_dir)),
        (TrendSignalConfig, load_trend_signal_config(data_dir)),
        (ActionTemplate, load_action_templates(data_dir)),
        (MvpStrategyTemplate, load_mvp_strategy_templates(data_dir)),
        (Competitor, load_competitors(data_dir)),
        (BmMapping, load_bm_mapping(data_dir)),
    ]


async def upsert_model(model: type[Any], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    primary_keys = [column.name for column in model.__table__.primary_key.columns]
    async with AsyncSessionLocal() as session:
        stmt = insert(model).values(rows)
        update_columns = {
            column.name: getattr(stmt.excluded, column.name)
            for column in model.__table__.columns
            if column.name not in {*primary_keys, "created_at"}
        }
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[getattr(model, key) for key in primary_keys],
                set_=update_columns,
            )
        )
        await session.commit()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import Postgres seed Excel workbooks into catalog tables."
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--dry-run", action="store_true", help="Parse XLSX files without DB writes.")
    args = parser.parse_args()

    datasets = load_all(args.data_dir)

    for model, rows in datasets:
        print(f"{model.__tablename__}: {len(rows)}")

    if args.dry_run:
        return

    for model, rows in datasets:
        await upsert_model(model, rows)

    print("Imported Postgres seed data.")


if __name__ == "__main__":
    asyncio.run(main())
