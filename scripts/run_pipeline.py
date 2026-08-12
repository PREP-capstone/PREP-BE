"""법령 PDF를 룰 추출 파이프라인에 투입하는 실행 진입점.

    python scripts/run_pipeline.py <document_id | PDF경로> [옵션]

    --dry-run       LLM 호출 없이 청킹까지만 (비용 0)
    --limit N       앞에서 N개 청크만 처리
    --stages A,B    실행할 Stage. 생략 시 manifest의 stages 사용
    --publish       DB 적재. **붙이지 않으면 화면 출력만 한다**
    --docs-dir PATH PDF 폴더 override
    --yes           비대화 환경에서 확인 프롬프트 건너뛰기

기본값이 "적재 안 함"인 이유는 검증되지 않은 룰이 실수로 들어가는 걸 막기 위해서다.

**그래프 대신 노드를 직접 순차 호출한다.** app/pipeline/graph.py는 publish까지 한 번에
이어지는 구조라 중간에서 끊을 수 없고, --limit를 적용할 지점(청킹 직후)도 없다.
호출하는 노드 함수와 순서는 graph.py의 _route_after_* 라우팅과 동일하게 유지한다.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):  # 한글 출력이 콘솔 코드페이지에 깨지지 않도록
    sys.stdout.reconfigure(encoding="utf-8")

from app.pipeline.nodes.chunk import chunk_document
from app.pipeline.nodes.extract_a import extract_A
from app.pipeline.nodes.extract_b import extract_B
from app.pipeline.nodes.extract_c import extract_C
from app.pipeline.nodes.ingest import ingest_document
from app.pipeline.nodes.publish import publish
from app.pipeline.nodes.validate import auto_validate

DEFAULT_DOCS_DIR = ROOT / ".." / "llm_documents"
MANIFEST_PATH = ROOT / "data" / "rule" / "manifest.csv"

_EXTRACTORS = {"A": extract_A, "B": extract_B, "C": extract_C}
_STAGE_TABLE = {"A": "gate_keywords", "B": "gate_matrix", "C": "correction_rules"}


# ---------- manifest ----------


def load_manifest() -> dict[str, dict[str, str]]:
    if not MANIFEST_PATH.exists():
        print(f"⚠️  manifest 없음: {MANIFEST_PATH}")
        return {}
    with MANIFEST_PATH.open(newline="", encoding="utf-8-sig") as f:
        return {row["document_id"]: row for row in csv.DictReader(f)}


def confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print(f"   비대화 환경이라 물어볼 수 없습니다. 진행하려면 --yes 를 붙이세요.")
        return False
    return input(f"   {question} [y/N] ").strip().lower() == "y"


def resolve_document(target: str, docs_dir: Path, assume_yes: bool) -> tuple[Path, str, dict]:
    """document_id 또는 PDF 경로 → (pdf_path, document_id, manifest_row)."""
    manifest = load_manifest()

    if target.lower().endswith(".pdf"):
        pdf_path = Path(target)
        if not pdf_path.is_absolute():
            pdf_path = (Path.cwd() / pdf_path).resolve()
    else:
        pdf_path = (docs_dir / f"{target}.pdf").resolve()

    document_id = pdf_path.stem  # 파일명(확장자 제외)이 곧 document_id
    row = manifest.get(document_id, {})

    if not pdf_path.exists():
        raise SystemExit(f"❌ PDF 없음: {pdf_path}")

    if not row:
        print(f"⚠️  manifest에 없는 문서입니다: {document_id}")
        if not confirm("그래도 진행할까요?", assume_yes):
            raise SystemExit("중단했습니다.")
    elif row.get("usage") != "RULE_BASE":
        print(f"⚠️  usage={row.get('usage')} 문서입니다 (RULE_BASE 아님): {row.get('title')}")
        print(f"   note: {row.get('note', '')}")
        if not confirm("그래도 파이프라인에 투입할까요?", assume_yes):
            raise SystemExit("중단했습니다.")

    return pdf_path, document_id, row


def resolve_stages(cli_stages: str | None, row: dict) -> list[str]:
    raw = cli_stages if cli_stages else row.get("stages", "")
    stages = [s.strip().upper() for s in raw.split(",") if s.strip()]
    if not stages:
        raise SystemExit("❌ 실행할 Stage를 정할 수 없습니다. --stages A,B 처럼 지정하세요.")
    unknown = [s for s in stages if s not in _EXTRACTORS]
    if unknown:
        raise SystemExit(f"❌ 알 수 없는 Stage: {unknown}")
    return stages


# ---------- 출력 ----------


def print_sample_chunks(chunks: list[dict], count: int = 3) -> None:
    print(f"\n--- 샘플 청크 {min(count, len(chunks))}개 ---")
    for chunk in chunks[:count]:
        print(f"\n[article_number] {chunk['article_number']!r}  ({len(chunk['content'])}자)")
        body = chunk["content"]
        print(body[:600] + ("…" if len(body) > 600 else ""))
    print("\n" + "-" * 60)


def print_drafts(drafts: list[dict]) -> None:
    print(f"\n--- 추출 draft {len(drafts)}건 ---")
    print(json.dumps(drafts, ensure_ascii=False, indent=2, default=str))
    print("-" * 60)


# ---------- 실행 ----------


async def run(args: argparse.Namespace) -> None:
    docs_dir = Path(args.docs_dir).resolve() if args.docs_dir else DEFAULT_DOCS_DIR.resolve()
    pdf_path, document_id, row = resolve_document(args.target, docs_dir, args.yes)
    stages = resolve_stages(args.stages, row)

    print(f"문서 : {document_id}")
    if row:
        print(f"제목 : {row.get('title')}")
    print(f"경로 : {pdf_path}")
    print(f"Stage: {','.join(stages)}   적재: {'예' if args.publish else '아니오(출력만)'}")

    # Stage C는 A/B가 published된 뒤에만 의미가 있다.
    if "C" in stages and {"A", "B"} & set(stages):
        print(
            "\n⚠️  Stage C를 A/B와 같은 실행에 넣었습니다.\n"
            "   Stage C는 **이미 publish된(active)** gate_keywords만 조회하므로,\n"
            "   같은 실행의 A/B 결과는 보지 못해 regulatory_score가 0점으로 나옵니다.\n"
            "   A/B를 먼저 --publish로 적재한 뒤 C를 별도 실행하세요."
        )
        if not confirm("그래도 진행할까요?", args.yes):
            raise SystemExit("중단했습니다.")

    total_steps = 2 if args.dry_run else 5
    state: dict = {"source_path": str(pdf_path), "document_id": document_id, "drafts": []}

    print(f"\n[1/{total_steps}] PDF 텍스트 추출 ...", end=" ", flush=True)
    state.update(ingest_document(state))
    print(f"{len(state['raw_text']):,}자")

    print(f"[2/{total_steps}] 청킹 ...", end=" ", flush=True)
    state.update(chunk_document(state))
    chunks = state["chunks"]
    print(f"{len(chunks)}개 청크")

    if args.offset or args.limit:
        start = args.offset or 0
        chunks = chunks[start : start + args.limit] if args.limit else chunks[start:]
        state["chunks"] = chunks
        span = ", ".join(c["article_number"] or "(무번호)" for c in chunks[:8])
        print(f"      --offset {start} --limit {args.limit} 적용 → {len(chunks)}개만 처리 [{span}]")

    non_empty = [c for c in chunks if c["content"].strip()]
    expected_calls = len(non_empty) * len(stages)

    if args.dry_run:
        print(f"\n예상 LLM 호출 수: {expected_calls}회 "
              f"(빈 청크 {len(chunks) - len(non_empty)}개 제외 × Stage {len(stages)}개)")
        print_sample_chunks(chunks)
        print("dry-run이라 여기서 종료합니다. LLM 호출 0회, 비용 0.")
        return

    print(f"[3/{total_steps}] 추출 ... (LLM 호출 예상 {expected_calls}회)")
    for stage in stages:
        before = len(state["drafts"])
        state.update(await _EXTRACTORS[stage](state))
        produced = len(state["drafts"]) - before
        print(f"      Stage {stage}: {produced}건 (LLM 호출 {len(non_empty)}회)")

    print(f"[4/{total_steps}] 검증 ...", end=" ", flush=True)
    submitted = len(state["drafts"])
    state.update(await auto_validate(state))
    passed = len(state["drafts"])
    failed = state["validation"]["failed_checks"]
    print(f"통과 {passed} / 탈락 {submitted - passed}")
    if failed:
        print(f"      탈락 사유: {', '.join(failed)}")

    print_drafts(state["drafts"])

    if not args.publish:
        print(f"[5/{total_steps}] 적재 ... 건너뜀 (--publish 없음)")
        return

    print(f"[5/{total_steps}] 적재 ...", end=" ", flush=True)
    counts: dict[str, int] = {}
    for draft in state["drafts"]:
        table = _STAGE_TABLE[draft["stage"]]
        counts[table] = counts.get(table, 0) + 1
    # publish()는 독립 호출 가능한 함수다 — 나중에 검수 게이트를 이 앞에 끼워 넣으면 된다.
    result = await publish(state)
    print(", ".join(f"{table} +{n}행" for table, n in sorted(counts.items())) or "0행")
    print(f"      rule_version_id: {result.get('rule_version_id')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="법령 PDF를 룰 추출 파이프라인에 투입한다.")
    parser.add_argument("target", help="document_id 또는 PDF 경로")
    parser.add_argument("--dry-run", action="store_true", help="LLM 호출 없이 청킹까지만")
    parser.add_argument("--limit", type=int, help="앞에서 N개 청크만 처리")
    parser.add_argument("--offset", type=int, default=0, help="앞의 N개 청크를 건너뛰고 시작")
    parser.add_argument("--stages", help="실행할 Stage (예: A,B). 생략 시 manifest 값")
    parser.add_argument("--publish", action="store_true", help="DB 적재 (없으면 출력만)")
    parser.add_argument("--docs-dir", help="PDF 폴더 경로 override")
    parser.add_argument("--yes", action="store_true", help="확인 프롬프트 건너뛰기")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
