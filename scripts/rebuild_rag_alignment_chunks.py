from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
CHUNKS_CSV = ROOT / "data" / "rag" / "evidence_chunks_draft.csv"
DOCUMENTS_CSV = ROOT / "data" / "rag" / "evidence_documents_draft.csv"
QUEUE_CSV = ROOT / "data" / "rag" / "chunking_queue.csv"

WELLNESS_DOC_ID = "kr-mfds-wellness-0091-03-20260212"
MEDICAL_ACT_DOC_ID = "kr-medical-act-20260407"
NONMEDICAL_2022_DOC_ID = "kr-mohw-nonmedical-health-guide-202209"
NONMEDICAL_2019_DOC_ID = "kr-mohw-nonmedical-healthcare-guide-20190521"

DEFAULT_SOURCE_DIR = ROOT / "data" / "rag" / "source_documents"
WELLNESS_FILE_NAME = "의료기기와+개인용+건강관리(웰니스)제품+판단기준(지침).pdf"
MEDICAL_ACT_FILE_NAME = "의료법(법률)(제21524호)(20260407).pdf"
NONMEDICAL_2022_FILE_NAME = "비의료 건강관리서비스 가이드라인_및_사례집(2차).pdf"


@dataclass
class TextLine:
    text: str
    page: int


@dataclass
class Chunk:
    document_id: str
    section_id: str
    section_title: str
    chunk_type: str
    text: str
    page_start: int
    page_end: int
    source_url: str
    local_file_path: str
    tag_regulatory: bool = True
    tag_privacy: bool = False
    tag_advertising: bool = False


def extract_pdf_text(pdf_path: Path) -> str:
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    with TemporaryDirectory() as tmpdir:
        txt_path = Path(tmpdir) / "document.txt"
        subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), str(txt_path)],
            check=True,
        )
        return txt_path.read_text(encoding="utf-8", errors="replace")


def iter_lines_with_pages(text: str) -> list[TextLine]:
    lines: list[TextLine] = []
    for page_number, page_text in enumerate(text.split("\f"), start=1):
        for line in page_text.splitlines():
            cleaned = clean_line(line)
            if cleaned:
                lines.append(TextLine(cleaned, page_number))
    return lines


def clean_line(line: str) -> str:
    text = line.replace("\x00", "").strip()
    text = re.sub(r"\s+", " ", text)
    if re.fullmatch(r"-\s*\d+\s*-", text):
        return ""
    if text.startswith("법제처 ") or text == "의료법":
        return ""
    return text


def normalize_roman(value: str) -> str:
    return {"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V"}[value]


def is_toc_line(line: str) -> bool:
    return "··" in line


def wellness_marker(line: str, chapter: str | None, number: str | None) -> tuple[str, str] | None:
    roman = re.match(r"^([ⅠⅡⅢⅣⅤ])\s+(.+)$", line)
    if roman and not is_toc_line(line):
        return normalize_roman(roman.group(1)), roman.group(2).strip()

    number_match = re.match(r"^([1-5])\.\s+(.+)$", line)
    if number_match and chapter and not is_toc_line(line):
        return f"{chapter}.{number_match.group(1)}", number_match.group(2).strip()

    letter_match = re.match(r"^([가나다라])\.\s+(.+)$", line)
    no_dot_letter_match = re.match(
        r"^([가나다라])\s+(위해도 판단 요소|고위해도|저위해도|생체현상 측정.*)$",
        line,
    )
    selected_letter_match = letter_match or no_dot_letter_match
    if selected_letter_match and chapter and number and not line.startswith(("예 ", "아니오 ")):
        return (
            f"{chapter}.{number}.{selected_letter_match.group(1)}",
            selected_letter_match.group(2).strip(),
        )

    return None


def build_wellness_chunks(wellness_pdf: Path) -> list[Chunk]:
    lines = iter_lines_with_pages(extract_pdf_text(wellness_pdf))
    chunks: list[tuple[str, str, list[TextLine]]] = []
    current_id: str | None = None
    current_title = ""
    current_lines: list[TextLine] = []
    chapter: str | None = None
    number: str | None = None
    started = False

    for item in lines:
        marker = wellness_marker(item.text, chapter, number)
        if marker:
            section_id, title = marker
            if section_id == "I":
                started = True
            if not started:
                continue

            if current_id and current_lines:
                chunks.append((current_id, current_title, current_lines))

            current_id = section_id
            current_title = title
            current_lines = [item]

            parts = section_id.split(".")
            chapter = parts[0]
            number = parts[1] if len(parts) >= 2 else None
            continue

        if started and current_id:
            current_lines.append(item)

    if current_id and current_lines:
        chunks.append((current_id, current_title, current_lines))

    output: list[Chunk] = []
    for section_id, title, section_lines in chunks:
        if section_id.startswith("V"):
            continue
        text = "\n".join(line.text for line in section_lines)
        output.append(
            Chunk(
                document_id=WELLNESS_DOC_ID,
                section_id=section_id,
                section_title=title,
                chunk_type="GUIDE_SECTION",
                text=text,
                page_start=min(line.page for line in section_lines),
                page_end=max(line.page for line in section_lines),
                source_url="https://www.mfds.go.kr/brd/m_210/view.do?Data_stts_gubun=C1004&company_cd=&company_nm=&itm_seq_1=0&itm_seq_2=0&multi_itm_seq=0&page=4&seq=15229&srchFr=&srchTo=&srchTp=0&srchWord=",
                local_file_path=source_document_label(wellness_pdf),
                tag_advertising=True,
            )
        )
    return output


def article_marker(line: str) -> str | None:
    match = re.match(r"^(제\d+조(?:의\d+)?)(?:\(|\s|$)", line)
    return match.group(1) if match else None


def build_medical_act_chunks(medical_act_pdf: Path) -> list[Chunk]:
    target_articles = {"제2조", "제27조", "제56조"}
    lines = iter_lines_with_pages(extract_pdf_text(medical_act_pdf))
    chunks: list[tuple[str, str, list[TextLine]]] = []
    current_article: str | None = None
    current_title = ""
    current_lines: list[TextLine] = []

    for item in lines:
        marker = article_marker(item.text)
        if marker:
            if current_article in target_articles and current_lines:
                chunks.append((current_article, current_title, current_lines))
            current_article = marker
            current_title = item.text.split(")", 1)[0] + ")" if ")" in item.text else item.text
            current_lines = [item]
            continue

        if current_article in target_articles:
            current_lines.append(item)

    if current_article in target_articles and current_lines:
        chunks.append((current_article, current_title, current_lines))

    output: list[Chunk] = []
    for article, title, article_lines in chunks:
        output.append(
            Chunk(
                document_id=MEDICAL_ACT_DOC_ID,
                section_id=article,
                section_title=title,
                chunk_type="LAW_ARTICLE",
                text="\n".join(line.text for line in article_lines),
                page_start=min(line.page for line in article_lines),
                page_end=max(line.page for line in article_lines),
                source_url="https://www.law.go.kr/LSW/lsLawLinkInfo.do?chrClsCd=010202&lsId=001788&lsJoLnkSeq=1000180469&print=print",
                local_file_path=source_document_label(medical_act_pdf),
            )
        )
    return output


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def chunk_to_row(chunk: Chunk, order: int) -> dict[str, str]:
    chunk_id = f"{chunk.document_id}__{chunk.section_id.replace('.', '_')}"
    return {
        "chunk_id": chunk_id,
        "document_id": chunk.document_id,
        "chunk_order": str(order),
        "section_id": chunk.section_id,
        "section_title": chunk.section_title,
        "chunk_type": chunk.chunk_type,
        "chunk_text": chunk.text,
        "page_start": str(chunk.page_start),
        "page_end": str(chunk.page_end),
        "char_count": str(len(chunk.text)),
        "tag_regulatory": str(chunk.tag_regulatory).lower(),
        "tag_privacy": str(chunk.tag_privacy).lower(),
        "tag_advertising": str(chunk.tag_advertising).lower(),
        "case_tag_advertising": "false",
        "case_tag_privacy": "false",
        "case_tag_medical_device": "false",
        "case_tag_health_functional_food": "false",
        "effective_date": "",
        "status": "active",
        "source_url": chunk.source_url,
        "local_file_path": chunk.local_file_path,
    }


def upsert_nonmedical_2022_document() -> None:
    fieldnames, rows = read_csv(DOCUMENTS_CSV)
    if any(row["document_id"] == NONMEDICAL_2022_DOC_ID for row in rows):
        return
    rows.append(
        {
            "document_id": NONMEDICAL_2022_DOC_ID,
            "law_id": "MOHW_NONMEDICAL_HEALTH_GUIDE_2ND",
            "title": "비의료 건강관리서비스 가이드라인 및 사례집(2차)",
            "doc_type": "GUIDE",
            "source_subtype": "MOHW_GUIDE",
            "issuing_org": "보건복지부",
            "jurisdiction": "KR",
            "rag_category": "의료규제 / 웰니스 / 비의료 건강관리",
            "effective_date": "",
            "publication_date": "2022-09-01",
            "status": "pending_source",
            "tag_regulatory": "true",
            "tag_privacy": "true",
            "tag_advertising": "false",
            "usage_scope": "BOTH",
            "source_url": "https://eiec.kdi.re.kr/policy/materialView.do?num=229658",
            "collection_source": "공식 보도자료 확인 / 원문 PDF 확보 필요",
            "processing_note": "룰베이스는 2차본(2022.9)을 인용한다. 공식 원문 PDF 확보 후 active 전환 및 청킹 필요.",
        }
    )
    write_csv(DOCUMENTS_CSV, fieldnames, rows)


def upsert_nonmedical_2022_queue(nonmedical_2022_pdf: Path) -> None:
    fieldnames, rows = read_csv(QUEUE_CSV)
    if any(row["document_id"] == NONMEDICAL_2022_DOC_ID for row in rows):
        return
    order_field = "queue_order" if "queue_order" in fieldnames else "priority"
    next_priority = max(int(row[order_field]) for row in rows if row.get(order_field, "").isdigit()) + 1
    rows.append(
        {
            order_field: str(next_priority),
            "phase": "phase_1_core",
            "document_id": NONMEDICAL_2022_DOC_ID,
            "title": "비의료 건강관리서비스 가이드라인 및 사례집(2차)",
            "status": "pending_source",
            "file_role": "PRIMARY_TEXT",
            "default_action": "needs_source",
            "chunk_unit": "장/절/Q&A 단위",
            "pages": "",
            "local_file_path": source_document_label(nonmedical_2022_pdf),
            "note": "룰베이스 correction_rules 29건 인용 문서. 2019년 1차본과 판본 불일치 방지를 위해 2차본 공식 PDF 확보 후 청킹.",
        }
    )
    write_csv(QUEUE_CSV, fieldnames, rows)


def annotate_nonmedical_2019_document() -> None:
    fieldnames, rows = read_csv(DOCUMENTS_CSV)
    for row in rows:
        if row["document_id"] == NONMEDICAL_2019_DOC_ID:
            note = row.get("processing_note", "")
            if "룰베이스 인용 문서는 2차본" not in note:
                row["processing_note"] = (
                    note
                    + " 룰베이스 인용 문서는 2차본(2022.9)이므로 이 1차본은 일반 참고용으로만 사용."
                ).strip()
    write_csv(DOCUMENTS_CSV, fieldnames, rows)


def rebuild_chunks(wellness_pdf: Path, medical_act_pdf: Path) -> None:
    fieldnames, rows = read_csv(CHUNKS_CSV)
    rows = [
        row
        for row in rows
        if row["document_id"] not in {WELLNESS_DOC_ID, MEDICAL_ACT_DOC_ID}
    ]

    generated = build_wellness_chunks(wellness_pdf) + build_medical_act_chunks(medical_act_pdf)
    start_order_by_doc: dict[str, int] = {}
    for chunk in generated:
        order = start_order_by_doc.get(chunk.document_id, 0) + 1
        start_order_by_doc[chunk.document_id] = order
        rows.append(chunk_to_row(chunk, order))

    write_csv(CHUNKS_CSV, fieldnames, rows)
    print(f"rebuilt {WELLNESS_DOC_ID}: {start_order_by_doc.get(WELLNESS_DOC_ID, 0)} chunks")
    print(f"rebuilt {MEDICAL_ACT_DOC_ID}: {start_order_by_doc.get(MEDICAL_ACT_DOC_ID, 0)} chunks")
    print(f"total chunks: {len(rows)}")


def default_source_dir() -> Path:
    return Path(os.environ.get("RAG_SOURCE_DIR", DEFAULT_SOURCE_DIR)).expanduser()


def resolve_source_path(source_dir: Path, override: Path | None, file_name: str) -> Path:
    return (override or source_dir / file_name).expanduser()


def source_document_label(path: Path) -> str:
    return str(Path("data") / "rag" / "source_documents" / path.name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild RAG chunks needed by rulebase evidence lookup.")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=default_source_dir(),
        help="Directory containing source PDFs. Can also be set with RAG_SOURCE_DIR.",
    )
    parser.add_argument("--wellness-pdf", type=Path, help="Override wellness guide PDF path.")
    parser.add_argument("--medical-act-pdf", type=Path, help="Override Medical Act PDF path.")
    parser.add_argument("--nonmedical-2022-pdf", type=Path, help="Override nonmedical guide 2nd edition PDF path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_dir = args.source_dir.expanduser()
    wellness_pdf = resolve_source_path(source_dir, args.wellness_pdf, WELLNESS_FILE_NAME)
    medical_act_pdf = resolve_source_path(source_dir, args.medical_act_pdf, MEDICAL_ACT_FILE_NAME)
    nonmedical_2022_pdf = resolve_source_path(source_dir, args.nonmedical_2022_pdf, NONMEDICAL_2022_FILE_NAME)

    try:
        rebuild_chunks(wellness_pdf, medical_act_pdf)
        upsert_nonmedical_2022_document()
        upsert_nonmedical_2022_queue(nonmedical_2022_pdf)
        annotate_nonmedical_2019_document()
    except Exception as exc:  # noqa: BLE001 - data repair script should surface parse failures.
        print(f"failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
