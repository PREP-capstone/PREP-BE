"""verb_substitution × 명사 조합으로 correction_rules 후보를 생성한다.

Stage C의 원천은 문서 추출이 아니라 조합 생성이다(app/pipeline/correction_terms.py
상단 설명, 룰_추출_기준_최종확정본.md §Stage C). LLM 호출이 없다 — 동사·safe_verb는
verb_substitution 테이블, 명사는 gate_keywords(DISEASE)+correction_terms.BIOMARKER_EXTRA
에서 가져와 코드로 직접 조합한다.

regulatory_score·derived_from_keyword_id는 extract_c.py의 `_derive_regulatory_score`를
그대로 재사용한다 — risky_text에 포함된 active gate_keywords를 부분문자열로 찾아 최고
점수를 채택하는 기존 로직이며, 생성된 risky_text에도 동일하게 적용된다.

기본 동작은 CSV 출력까지다. --publish를 붙여야 DB에 적재한다. auto_validate를 거치지
않는다 — gate_matrix 6칸 시드와 같은 이유다: 이건 원문에서 뽑은 게 아니라 생성물이라
인용 대조 자체가 성립하지 않는다.

    python scripts/generate_correction_rules.py            # CSV만 생성 (기본, 검토용)
    python scripts/generate_correction_rules.py --publish   # 검토 후 DB에 적재
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):  # 한글 출력이 콘솔 코드페이지에 깨지지 않도록
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import func, select

from app.db.models import CorrectionRule, GateKeyword, RuleVersion, VerbSubstitution
from app.db.session import AsyncSessionLocal
from app.pipeline.correction_terms import BIOMARKER_EXTRA, NOUN_CLASSIFICATION
from app.pipeline.nodes.extract_c import _derive_regulatory_score
from app.pipeline.nodes.publish import publish

DEFAULT_OUT = ROOT / "data" / "rule" / "correction_rules_generated.csv"

# "측정"은 수치 표시·알람 여부에 따라 PASS/FAIL이 갈린다(웰니스판단기준 0091-03
# IV.3 판단사례, 2026-08-13 팀 원문 재대조로 확인). 텍스트 매칭이 잡을 수 있는
# 층위가 아니므로 룰 구조는 바꾸지 않고 safe_text에 조건만 덧붙인다.
MEASURE_CAVEAT = " (수치·알람 기능 없이)"

_CSV_FIELDS = [
    "risky_text",
    "safe_text",
    "regulatory_score",
    "advertising_score",
    "derived_from_keyword_id",
    "legal_basis_doc",
    "legal_basis_article",
    "source_verb",
]


async def _load_noun_pools() -> dict[str, list[str]]:
    async with AsyncSessionLocal() as session:
        rows = await session.scalars(
            select(GateKeyword.keyword)
            .join(RuleVersion, RuleVersion.rule_version_id == GateKeyword.rule_version_id)
            .where(
                RuleVersion.status == "active",
                GateKeyword.type == "DISEASE",
                GateKeyword.keyword_category == "DATA_TYPE",
            )
            .distinct()
        )
        keywords = list(rows.all())

    pools: dict[str, list[str]] = {"질병명": [], "생체지표": list(BIOMARKER_EXTRA)}
    for keyword in keywords:
        noun_class = NOUN_CLASSIFICATION.get(keyword)
        if noun_class is None:
            print(f"  ⚠️ 미분류 명사 건너뜀: {keyword!r} — correction_terms.py에 분류 추가 필요")
            continue
        pools[noun_class].append(keyword)
    return pools


async def _load_verbs() -> list[VerbSubstitution]:
    async with AsyncSessionLocal() as session:
        return list((await session.scalars(select(VerbSubstitution))).all())


async def _load_active_keywords() -> list[GateKeyword]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(GateKeyword)
            .join(RuleVersion, RuleVersion.rule_version_id == GateKeyword.rule_version_id)
            .where(RuleVersion.status == "active")
        )
        return list(result.scalars().all())


async def _existing_active_risky_texts() -> set[str]:
    async with AsyncSessionLocal() as session:
        rows = await session.scalars(
            select(func.lower(CorrectionRule.risky_text))
            .join(RuleVersion, RuleVersion.rule_version_id == CorrectionRule.rule_version_id)
            .where(RuleVersion.status == "active")
        )
        return set(rows.all())


def combos(verb: VerbSubstitution, pools: dict[str, list[str]]):
    """verb 1행이 만들어내는 (risky_text, safe_text) 쌍을 전부 낸다."""
    if verb.standalone:
        yield verb.verb, verb.safe_verb
        return
    for noun_class in filter(None, verb.noun_classes.split("|")):
        for noun in pools.get(noun_class, []):
            safe_text = f"{noun} {verb.safe_verb}"
            if verb.verb == "측정":
                safe_text += MEASURE_CAVEAT
            yield f"{noun} {verb.verb}", safe_text


async def generate(out_path: Path, do_publish: bool) -> None:
    pools = await _load_noun_pools()
    verbs = await _load_verbs()
    active_keywords = await _load_active_keywords()
    existing = await _existing_active_risky_texts()

    if not verbs:
        print("verb_substitution이 비어 있습니다 — scripts/seed_verb_substitution.py를 먼저 실행하세요.")
        return

    print(f"명사 풀: 질병명 {len(pools['질병명'])}개, 생체지표 {len(pools['생체지표'])}개")

    rows: list[dict] = []
    skipped_existing = 0
    for verb in verbs:
        for risky_text, safe_text in combos(verb, pools):
            if risky_text.lower() in existing:
                skipped_existing += 1
                continue
            regulatory_score, derived_from_keyword_id = _derive_regulatory_score(
                risky_text, active_keywords
            )
            rows.append(
                {
                    "risky_text": risky_text,
                    "safe_text": safe_text,
                    "regulatory_score": regulatory_score,
                    # 이 갈래는 의료행위·약무행위 표현이지 광고 표현이 아니다. 광고 축은
                    # 별표7 갈래(별도 스크립트/프롬프트)에서만 채운다.
                    "advertising_score": 0,
                    "derived_from_keyword_id": derived_from_keyword_id,
                    "legal_basis_doc": verb.legal_basis_doc,
                    "legal_basis_article": verb.legal_basis_article,
                    "source_verb": verb.verb,
                }
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"생성 {len(rows)}행 (기존 active와 중복 {skipped_existing}건 제외) → {out_path}")
    if rows:
        zero_score = sum(1 for r in rows if r["regulatory_score"] == 0)
        print(f"  regulatory_score=0인 행: {zero_score}건 (명사·동사 둘 다 gate_keywords 매칭 실패 — 점검 필요)")

    if not do_publish:
        print("--publish 없이 종료 — CSV만 생성했습니다. 검토 후 --publish로 재실행하세요.")
        return
    if not rows:
        print("적재할 신규 행이 없습니다.")
        return

    drafts = [
        {
            "stage": "C",
            "fields": {
                "risky_text": r["risky_text"],
                "safe_text": r["safe_text"],
                "regulatory_score": r["regulatory_score"],
                "advertising_score": r["advertising_score"],
                "derived_from_keyword_id": r["derived_from_keyword_id"],
                "legal_basis": {
                    "document_id": r["legal_basis_doc"],
                    "article": r["legal_basis_article"],
                    "quote": "",  # correction_rules는 quote를 저장하지 않는다(생성물이라 원문 인용 없음)
                },
            },
            "legal_basis": {
                "document_id": r["legal_basis_doc"],
                "article": r["legal_basis_article"],
                "quote": "",
            },
        }
        for r in rows
    ]
    result = await publish({"drafts": drafts, "rule_version_id": None})
    async with AsyncSessionLocal() as session:
        version = await session.scalar(
            select(RuleVersion.version).where(RuleVersion.rule_version_id == result["rule_version_id"])
        )
    print(f"correction_rules: {len(drafts)}행 발행 (rule_version={version})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="verb_substitution × 명사 조합으로 correction_rules 생성"
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="CSV 출력 경로")
    parser.add_argument("--publish", action="store_true", help="검토 후 DB에 적재")
    args = parser.parse_args()
    asyncio.run(generate(Path(args.out), args.publish))


if __name__ == "__main__":
    main()
