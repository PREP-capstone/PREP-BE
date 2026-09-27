"""국가법령정보센터(law.go.kr) Open API 클라이언트.

점검 스크립트(scripts/check_law_amendments.py)와 관리자 검수 API(app/api/rule_documents.py)가
같이 쓴다.

**PDF 대신 이 API로 조문을 받는 이유**: 본문 API는 조문 단위로 이미 나뉜 구조화 JSON을 준다
(조문번호/조문제목/항/호/조문시행일자/조문변경여부). pypdf로 PDF를 긁으면 chunk.py가
NUL 문자·목차 줄·헤딩 오인식 같은 걸 일일이 우회해야 하는데, 법령 문서는 이 API로 받으면
그 문제 자체가 사라진다. 다만 지침서·안내서류(판단가이드)는 law.go.kr에 등록된 법령이
아니라 여전히 PDF 경로를 써야 한다.
"""

from __future__ import annotations

import uuid

import httpx

from app.core.config import settings

_BASE_URL = "http://www.law.go.kr/DRF"
_TIMEOUT = 15.0


class LawApiUnavailable(RuntimeError):
    """OC 키 미설정 또는 law.go.kr 호출 실패."""


def _require_oc() -> str:
    if not settings.law_go_kr_oc:
        raise LawApiUnavailable("LAW_GO_KR_OC가 설정돼 있지 않습니다 (.env 확인)")
    return settings.law_go_kr_oc


async def search_laws(query: str, display: int = 50) -> list[dict]:
    """법령명으로 검색. 검색이 느슨해서("의료법" → "공공보건의료에 관한 법률"이 먼저 나옴)
    호출부가 법령명한글을 직접 확인해야 한다 — find_exact_law 참고."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{_BASE_URL}/lawSearch.do",
            params={
                "OC": _require_oc(),
                "target": "law",
                "type": "JSON",
                "query": query,
                "display": display,
            },
        )
        resp.raise_for_status()
    laws = resp.json().get("LawSearch", {}).get("law", [])
    if isinstance(laws, dict):
        laws = [laws]
    return laws


async def find_exact_law(title: str) -> dict | None:
    """법령명한글이 정확히 일치하는 건만 고른다."""
    for law in await search_laws(title):
        if law.get("법령명한글") == title:
            return law
    return None


def article_body(article: dict) -> str:
    """조문 본문을 항/호까지 펼친 한 덩어리 텍스트로 만든다."""
    hangs = article.get("항")
    if not hangs:
        return article.get("조문내용", "")
    if isinstance(hangs, dict):
        hangs = [hangs]
    lines: list[str] = []
    for hang in hangs:
        lines.append(hang.get("항내용", ""))
        hos = hang.get("호")
        if not hos:
            continue
        if isinstance(hos, dict):
            hos = [hos]
        lines.extend("  " + ho.get("호내용", "") for ho in hos)
    return "\n".join(line for line in lines if line)


def article_label(article: dict) -> str:
    """"제2조" / "제2조의2" 형태의 정식 조문 표기.

    API는 가지조문(제2조의2)도 조문번호를 본조와 같은 "2"로 주고 `조문가지번호`로만
    구분한다. 이걸 무시하면 제2조를 고른 줄 알았는데 제2조의2까지 딸려오고, 둘 다
    legal_basis_article이 "제2조"로 기록돼 근거 조문이 틀리게 남는다(2026-09-27 실측).
    """
    base = f"제{article.get('조문번호')}조"
    branch = article.get("조문가지번호")
    return f"{base}의{branch}" if branch else base


def article_key(article: dict) -> str:
    """조문 선택용 고유 키. 본조는 "2", 가지조문은 "2-2"."""
    branch = article.get("조문가지번호")
    return f"{article.get('조문번호')}-{branch}" if branch else str(article.get("조문번호"))


async def fetch_articles(mst: str) -> list[dict]:
    """법령 본문의 조문 목록. 조문제목이 없는 항목(장/절 제목 줄)은 제외한다 — 추출할
    내용이 없고 청크로 만들면 LLM 호출만 낭비된다."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            f"{_BASE_URL}/lawService.do",
            params={"OC": _require_oc(), "target": "law", "type": "JSON", "MST": mst},
        )
        resp.raise_for_status()
    articles = resp.json().get("법령", {}).get("조문", {}).get("조문단위", [])
    if isinstance(articles, dict):
        articles = [articles]
    return [
        {
            "조문번호": a.get("조문번호"),
            "조문가지번호": a.get("조문가지번호"),
            "조문표기": article_label(a),
            "조문키": article_key(a),
            "조문제목": a.get("조문제목"),
            "조문시행일자": a.get("조문시행일자"),
            "조문변경여부": a.get("조문변경여부"),
            "본문": article_body(a),
        }
        for a in articles
        if a.get("조문제목")
    ]


def changed_articles(articles: list[dict]) -> list[dict]:
    return [a for a in articles if a.get("조문변경여부") == "Y"]


def articles_to_chunks(articles: list[dict], document_id: str) -> list[dict]:
    """조문 리스트를 파이프라인 Chunk 형태로 변환한다(chunk_document 출력과 같은 모양).

    article_number 표기는 article_ref.normalize_article 규칙("제24조")에 맞춘다 —
    이 값이 legal_basis_article로 흘러가 RAG evidence_chunks.section_id와 조인되는
    키라서, 표기가 어긋나면 근거 조회가 조용히 실패한다.
    """
    chunks = []
    for article in articles:
        body = article.get("본문") or ""
        if not body.strip():
            continue
        # fetch_articles를 거치지 않은 원본 dict가 들어올 수도 있어 표기를 다시 계산한다.
        article_number = article.get("조문표기") or article_label(article)
        chunks.append(
            {
                "chunk_id": str(uuid.uuid4()),
                "document_id": document_id,
                "article_number": article_number,
                "section_path": article_number,
                "content": body,
                "source": "own",
            }
        )
    return chunks
