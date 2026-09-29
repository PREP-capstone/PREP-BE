"""law.go.kr 조문 → Chunk 변환과, 청크가 미리 주어졌을 때 PDF 경로를 건너뛰는지 검증한다.

법령은 본문 API가 조문 단위로 나뉜 텍스트를 주므로 pypdf/chunk.py를 태울 이유가 없다.
이 경로가 깨지면 조용히 PDF 경로로 빠지면서 source_path가 없어 터지거나, 반대로 청크를
덮어써서 선택한 조문이 아닌 전체 문서가 들어가게 된다.
"""

import uuid
from unittest.mock import patch

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import delete

import app.pipeline.graph as graph_module
from app.db.models import GateKeyword, RuleReviewQueue
from app.db.session import AsyncSessionLocal
from app.domain.law_api import (
    _is_live_article,
    article_body,
    article_key,
    article_label,
    articles_to_chunks,
)
from app.pipeline.graph import build_graph

pytestmark = pytest.mark.db


def test_article_body_expands_hang_and_ho() -> None:
    article = {
        "조문내용": "제23조(민감정보의 처리 제한)",
        "항": [
            {
                "항내용": "①개인정보처리자는 ... 처리하여서는 아니 된다.",
                "호": [
                    {"호내용": "1. 정보주체에게 ... 동의를 받은 경우"},
                    {"호내용": "2. 법령에서 ... 허용하는 경우"},
                ],
            }
        ],
    }
    body = article_body(article)
    assert "①개인정보처리자는" in body
    assert "  1. 정보주체에게" in body
    assert "  2. 법령에서" in body


def test_article_body_falls_back_to_조문내용_when_no_항() -> None:
    """가지조문처럼 항 구조 없이 조문내용에 본문이 통째로 담긴 경우."""
    article = {"조문내용": "제32조의3(자료 제공 요청) 식품의약품안전처장은 ...", "항": None}
    assert article_body(article).startswith("제32조의3")


def test_drops_chapter_heading_rows() -> None:
    """장/절 제목 줄(조문여부="전문")은 추출할 내용이 없다."""
    assert not _is_live_article({"조문여부": "전문", "조문내용": "        제2장 의료인"})


def test_drops_deleted_article() -> None:
    """삭제된 조문은 반드시 빠져야 한다 — find_missing_citations가 "현행 법령에 있는 조문"을
    fetch_articles 결과로 잡으므로, 여기 남으면 근거 소실 감지가 무력화된다."""
    assert not _is_live_article({"조문여부": "조문", "조문내용": "제7조 삭제 <2024.9.20>"})
    assert not _is_live_article({"조문여부": "조문", "조문내용": "제27조의2 삭제 <2015.12.22>"})


def test_keeps_untitled_but_substantive_article() -> None:
    """제목만 없고 내용은 있는 실질 조문(의료법 제88조의3, 2026-09-27 실측). 조문제목 유무로
    걸렀을 때 조문 선택 목록에도 안 뜨고 청크로도 안 들어가던 케이스다."""
    assert _is_live_article(
        {
            "조문여부": "조문",
            "조문번호": "88",
            "조문가지번호": "3",
            "조문제목": None,
            "조문내용": "제88조의3",
            "항": [{"항내용": "벌칙 관련 조문 본문"}],
        }
    )


def test_skips_chunk_for_article_without_body() -> None:
    """본문이 조문표기뿐인 조문(의료법 제88조의3)은 청크로 만들지 않는다 — 조문 목록에는
    남지만(근거 소실 감지 기준) 추출할 원문이 없다."""
    articles = [
        {"조문표기": "제88조의3", "본문": "제88조의3"},
        {"조문표기": "제27조", "본문": "①의료인이 아니면 누구든지 의료행위를 할 수 없으며"},
    ]
    chunks = articles_to_chunks(articles, "kr-medical-act-20260407")
    assert [c["article_number"] for c in chunks] == ["제27조"]


def test_branch_article_gets_distinct_label_and_key() -> None:
    """가지조문(제2조의2)은 API가 조문번호를 본조와 같은 "2"로 주고 조문가지번호로만
    구분한다. 이걸 무시하면 제2조를 고를 때 제2조의2("의료기기의 날")까지 딸려오고
    둘 다 legal_basis_article이 "제2조"로 기록된다(2026-09-27 실측으로 발견한 버그)."""
    base = {"조문번호": "2", "조문제목": "정의"}
    branch = {"조문번호": "2", "조문가지번호": "2", "조문제목": "의료기기의 날"}

    assert article_label(base) == "제2조"
    assert article_label(branch) == "제2조의2"
    assert article_key(base) == "2"
    assert article_key(branch) == "2-2"
    assert article_key(base) != article_key(branch)


def test_chunk_keeps_branch_article_notation() -> None:
    chunks = articles_to_chunks(
        [{"조문번호": "2", "조문가지번호": "2", "조문제목": "의료기기의 날", "본문": "① 매년 5월 29일을 ..."}],
        "kr-medical-device-act-20260701",
    )
    assert chunks[0]["article_number"] == "제2조의2"


def test_articles_to_chunks_uses_normalized_article_number() -> None:
    """article_number는 legal_basis_article로 흘러가 RAG section_id와 조인되는 키라
    "제2조" 형태여야 한다."""
    chunks = articles_to_chunks(
        [{"조문번호": "2", "조문제목": "정의", "본문": "이 법에서 ..."}], "kr-medical-device-act-20260701"
    )
    assert len(chunks) == 1
    assert chunks[0]["article_number"] == "제2조"
    assert chunks[0]["document_id"] == "kr-medical-device-act-20260701"
    assert chunks[0]["source"] == "own"


def test_articles_to_chunks_skips_empty_body() -> None:
    chunks = articles_to_chunks([{"조문번호": "1", "조문제목": "목적", "본문": "   "}], "doc")
    assert chunks == []


async def test_graph_skips_pdf_path_when_chunks_are_prefilled() -> None:
    """청크를 미리 채워 넣으면 ingest_document(PDF 읽기)를 타지 않아야 한다 —
    source_path가 없는 상태로 PDF 경로를 타면 그대로 터진다."""
    keyword = f"조문투입테스트_{uuid.uuid4().hex[:8]}"
    thread_id = str(uuid.uuid4())
    document_id = f"kr-test-law-{uuid.uuid4().hex[:8]}"
    chunk = articles_to_chunks(
        [{"조문번호": "2", "조문제목": "정의", "본문": "이 법에서 테스트 조문이라 함은 ..."}], document_id
    )[0]

    draft = {
        "stage": "A",
        "fields": {
            "type": "DISEASE",
            "keyword": keyword,
            "keyword_category": "DATA_TYPE",
            "data_type_focus": "NONE",
            "verdict": "FAIL_CANDIDATE",
            "weight": 2,
            "legal_basis": {
                "document_id": document_id,
                "article": "제2조",
                "quote": chunk["content"],
            },
        },
        "legal_basis": {
            "document_id": document_id,
            "article": "제2조",
            "quote": chunk["content"],
        },
        "source_chunk_id": chunk["chunk_id"],
    }

    def _explode(_state):  # ingest_document가 호출되면 테스트 실패
        raise AssertionError("청크가 있는데도 PDF 경로(ingest_document)를 탔다")

    with (
        patch.object(graph_module, "ingest_document", _explode),
        patch.object(graph_module, "extract_A", lambda state: {"drafts": [draft]}),
    ):
        graph = build_graph(checkpointer=InMemorySaver())
        config = {"configurable": {"thread_id": thread_id}}
        result = await graph.ainvoke(
            {
                "document_id": document_id,
                "document_category": "법령규제문서",
                "target_stages": ["A"],
                "chunks": [chunk],
                "raw_text": "",
                "current_chunk_id": None,
                "current_stage": None,
                "drafts": [],
                "derived_values": {},
                "validation": None,
                "retry_count": 0,
                "rule_version_id": None,
                "rejected_drafts": [],
            },
            config=config,
        )
        assert "__interrupt__" in result, "human_review에서 멈춰야 한다"

    try:
        async with AsyncSessionLocal() as session:
            queue_row = await session.get(RuleReviewQueue, thread_id)
        assert queue_row is not None
        assert len(queue_row.items) == 1
        assert queue_row.items[0]["draft"]["fields"]["keyword"] == keyword
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(RuleReviewQueue).where(RuleReviewQueue.thread_id == thread_id)
            )
            await session.execute(delete(GateKeyword).where(GateKeyword.keyword == keyword))
            await session.commit()
