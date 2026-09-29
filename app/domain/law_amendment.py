"""법령 개정 감지 결과를 "우리 룰과 관련 있는지"로 가르는 로직.

개정 감지 자체(공포번호/시행일자 비교)보다 이쪽이 실제로 중요하다. 법은 수시로 바뀌는데
대부분은 우리가 인용하지 않는 조문이라, 교집합을 안 내면 배너가 무관한 알림으로 가득 차서
정작 대응이 필요한 건을 묻어버린다.

실측(2026-09-27): 감지된 개정 4건이 전부 무관이었다.
- 의료법은 제5조(면허 요건)가 바뀌었지만 우리가 인용하는 건 제27조(무면허 의료행위)
- 약사법은 제3조(약사 자격)가 바뀌었지만 우리는 제2·23·24·44조를 인용
- 의료기기법은 제24조의2~5 등이 바뀌었지만 우리는 제2조(정의)를 인용
- 개인정보 보호법은 gate_matrix/correction_rules에 근거 룰 자체가 없음

주의: gate_keywords에는 legal_basis 컬럼이 없어(publish.py 참조) 교집합 대상이 아니다 —
Stage A 키워드의 근거 조문은 현재 DB에 저장되지 않는다는 기존 제약을 그대로 따른다.
"""

from __future__ import annotations

import re

from sqlalchemy import select

from app.db.models import CorrectionRule, GateMatrix
from app.db.rule_version_queries import resolve_active_rule_version_ids
from app.db.session import AsyncSessionLocal

# 우리 쪽 표기는 "제27조" 형태(article_ref.normalize_article 규칙), law.go.kr API는
# 조문번호를 "27"처럼 숫자만 준다. 비교하려면 한쪽으로 맞춰야 한다.
_ARTICLE_NO = re.compile(r"제\s*(\d+)\s*조")


def _article_numbers(article_label: str | None) -> set[str]:
    """"제27조", "제24조의2" 같은 표기에서 조문 번호만 뽑는다.

    가지번호(제24조의2)는 본조 번호(24)로 취급한다 — 가지조문이 신설·개정되면 본조
    체계 전체를 같이 봐야 하는 경우가 많아, 보수적으로 관련 있다고 판단하는 편이 낫다.
    """
    if not article_label:
        return set()
    return set(_ARTICLE_NO.findall(article_label))


async def load_cited_articles(document_id: str) -> set[str]:
    """이 문서(document_id)를 근거로 삼는 active 룰이 인용 중인 조문 번호 집합."""
    version_ids = await resolve_active_rule_version_ids()
    async with AsyncSessionLocal() as session:
        matrix = (
            await session.scalars(
                select(GateMatrix.legal_basis_article).where(
                    GateMatrix.rule_version_id.in_(version_ids),
                    GateMatrix.legal_basis_doc == document_id,
                )
            )
        ).all()
        rules = (
            await session.scalars(
                select(CorrectionRule.legal_basis_article).where(
                    CorrectionRule.rule_version_id.in_(version_ids),
                    CorrectionRule.legal_basis_doc == document_id,
                )
            )
        ).all()

    cited: set[str] = set()
    for label in list(matrix) + list(rules):
        cited |= _article_numbers(label)
    return cited


def filter_related_articles(changed_articles: list[dict], cited_numbers: set[str]) -> list[dict]:
    """바뀐 조문 중 우리가 인용 중인 조문만 추린다."""
    return [a for a in changed_articles if str(a.get("조문번호")) in cited_numbers]


def find_missing_citations(cited_numbers: set[str], current_articles: list[dict]) -> list[str]:
    """우리 룰이 인용하는 조문 중 현행 법령에 더 이상 없는 조문 번호.

    설계 단계에선 "기존 룰의 legal_basis.quote가 현행 조문에 남아있는지" 검사하려 했으나,
    확인해보니 gate_matrix/correction_rules에는 quote 컬럼이 아예 없다 — 인용문은 런타임에
    RAG evidence_chunks에서 조회한다(judgement.py `_fill_quotes`). 그래서 실제로 깨지는 건
    인용문이 아니라 **조인 키인 조문 번호**다. 조문이 삭제되면 그 룰은 근거를 잃고,
    judgement API가 사용자에게 근거를 못 보여준다.

    "제25조의4 삭제 <2026.9.15>" 같은 케이스가 실제로 있었다(의료기기법, 2026-09-27 확인).
    """
    existing = {str(a.get("조문번호")) for a in current_articles}
    return sorted(no for no in cited_numbers if no not in existing)


def decide_relevance(document_id: str | None, related_articles: list[dict]) -> str:
    """document_id 매핑이 없으면 교집합을 낼 수 없으므로 보수적으로 related로 둔다 —
    "판단 불가"를 "무관"으로 접어버리면 조용히 놓치게 된다."""
    if document_id is None:
        return "related"
    return "related" if related_articles else "unrelated"
