"""국가법령정보센터 Open API로 룰베이스가 추적 중인 법령의 개정 여부를 점검한다.

3단계로 확인한다.
1. 목록 API(가벼움)로 공포번호/시행일자가 우리 기록과 다른지 거른다.
2. 다른 것만 본문 API로 조문 단위 `조문변경여부`(Y/N)를 조회해 실제로 바뀐 조문을 뽑는다.
3. 바뀐 조문 ∩ 우리 룰이 인용 중인 조문을 계산해 관련/무관을 가른다(app/domain/law_amendment.py).

결과는 law_amendment_alert 테이블에 남고 /admin/rules 배너로 뜬다 — 콘솔에만 찍으면
누가 돌려보기 전엔 아무도 모르기 때문이다. 같은 개정건(법령명+공포번호)은 여러 번 돌려도
한 행만 유지한다.

문서명은 law.go.kr의 "법령명한글"과 정확히 일치해야 한다 — 느슨한 키워드 검색은
"의료법" 검색 시 "공공보건의료에 관한 법률"을 먼저 반환하는 등 관계없는 법을 앞세우는
경우가 있어(2026-09-27 확인), 결과 중 제목이 정확히 일치하는 것만 채택한다.

    python scripts/check_law_amendments.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.db.models import LawAmendmentAlert
from app.db.session import AsyncSessionLocal
from app.domain import law_api
from app.domain.law_amendment import (
    decide_relevance,
    filter_related_articles,
    find_missing_citations,
    load_cited_articles,
)

# db_구축_설계서.md §1.5 기준 기록값. document_id는 룰 테이블의 legal_basis_doc과
# 대조해 교집합을 내는 키다. "판단가이드"류(지침서/안내서/가이드라인)는 law.go.kr에
# 등록된 정식 법령이 아니라 이 API로 추적 불가 — 대상은 법률/시행령/시행규칙뿐이다.
TRACKED_LAWS = [
    {
        "title": "의료기기법",
        "document_id": "kr-medical-device-act-20260701",
        "known_promulgation_no": 21263,
        "known_effective_date": "20260701",
    },
    {
        "title": "의료기기법 시행규칙",
        "document_id": "kr-medical-device-act-rule-20260701",
        "known_promulgation_no": 2127,
        "known_effective_date": "20260701",
    },
    {
        "title": "의료법",
        "document_id": "kr-medical-act-20260407",
        "known_promulgation_no": 21524,
        "known_effective_date": "20260407",
    },
    {
        "title": "약사법",
        "document_id": "kr-pharmaceutical-affairs-act-20260621",
        "known_promulgation_no": 21109,
        "known_effective_date": "20260621",
    },
    {
        "title": "개인정보 보호법",
        "document_id": "kr-pipa-active-20251002",
        "known_promulgation_no": 20897,
        "known_effective_date": "20251002",
    },
]


async def _save_alert(
    tracked: dict,
    law: dict,
    changed: list[dict],
    related: list[dict],
    relevance: str,
    missing: list[str],
) -> None:
    """같은 개정건(법령명+공포번호)은 한 행만 유지한다 — 스크립트를 여러 번 돌려도
    배너에 중복으로 쌓이면 안 된다. 이미 처리(resolved/dismissed)한 건은 status를
    되돌리지 않고 내용만 갱신한다."""
    values = {
        "law_title": tracked["title"],
        "document_id": tracked["document_id"],
        "known_promulgation_no": tracked["known_promulgation_no"],
        "latest_promulgation_no": int(law.get("공포번호") or 0),
        "known_effective_date": tracked["known_effective_date"],
        "latest_effective_date": law.get("시행일자") or "",
        "changed_articles": changed,
        "related_articles": related,
        "missing_citations": missing,
        "relevance": relevance,
        "status": "open",
    }
    async with AsyncSessionLocal() as session:
        stmt = pg_insert(LawAmendmentAlert).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_law_amendment_alert_law_promulgation",
            set_={
                "changed_articles": changed,
                "related_articles": related,
                "missing_citations": missing,
                "relevance": relevance,
                "latest_effective_date": values["latest_effective_date"],
            },
        )
        await session.execute(stmt)
        await session.commit()


async def main() -> None:
    if not settings.law_go_kr_oc:
        print("LAW_GO_KR_OC가 설정돼 있지 않습니다 (.env 확인)")
        return

    for tracked in TRACKED_LAWS:
        title = tracked["title"]
        law = await law_api.find_exact_law(title)
        if law is None:
            print(f"[확인 필요] {title}: law.go.kr에서 제목이 정확히 일치하는 법령을 못 찾음")
            continue

        latest_no = int(law.get("공포번호") or 0)
        latest_date = law.get("시행일자")
        if latest_no == tracked["known_promulgation_no"] and latest_date == tracked["known_effective_date"]:
            print(f"[일치] {title}: 공포번호 {latest_no}, 시행일자 {latest_date}")
            continue

        articles = await law_api.fetch_articles(law["법령일련번호"])
        changed = law_api.changed_articles(articles)
        cited = await load_cited_articles(tracked["document_id"])
        related = filter_related_articles(changed, cited)
        missing = find_missing_citations(cited, articles)
        # 인용 조문이 사라졌으면 변경 조문과 겹치지 않아도 대응이 필요하다 —
        # 그 룰은 이미 근거를 잃은 상태다.
        relevance = "related" if missing else decide_relevance(tracked["document_id"], related)
        await _save_alert(tracked, law, changed, related, relevance, missing)

        mark = "관련" if relevance == "related" else "무관"
        print(
            f"[개정 감지 · {mark}] {title}: 공포번호 {tracked['known_promulgation_no']}"
            f" -> {latest_no}, 시행 {tracked['known_effective_date']} -> {latest_date}"
        )
        print(f"  변경 조문 {len(changed)}건, 우리가 인용 중인 조문 {sorted(cited) or '없음'}")
        for article in related:
            print(
                f"  ⚠️ {article['조문표기']} {article['조문제목']} "
                f"(시행 {article['조문시행일자']}) — 우리 룰이 인용 중"
            )
        for article_label in missing:
            print(f"  🚨 {article_label} — 우리 룰이 인용하는데 현행 법령에 없음(삭제·이동)")

    print("\n결과는 law_amendment_alert 테이블에 기록됐습니다 — /admin/rules 배너에서 확인하세요.")


if __name__ == "__main__":
    asyncio.run(main())
