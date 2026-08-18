"""RAG chunk 조회 응답 정렬 회귀 테스트.

lookup_rag_chunks는 DB의 chunk_order가 아니라 caller가 보낸 section_ids 순서로
청크를 반환해야 한다 — 매칭된 규칙이 인용한 조문 순서를 그대로 보존해야 하기 때문.
"""

from dataclasses import dataclass

from app.api.rag import order_chunks_by_requested_sections


@dataclass
class FakeChunk:
    section_id: str | None
    chunk_order: int


def test_orders_chunks_by_requested_section_order_not_db_order() -> None:
    # DB는 chunk_order 기준(B, A)으로 반환하지만, 요청은 A를 먼저 원했다.
    chunk_a = FakeChunk(section_id="A", chunk_order=2)
    chunk_b = FakeChunk(section_id="B", chunk_order=1)

    ordered = order_chunks_by_requested_sections([chunk_b, chunk_a], ["A", "B"])

    assert [c.section_id for c in ordered] == ["A", "B"]


def test_duplicate_section_id_keeps_first_occurrence_position() -> None:
    """회귀: section_ids=[A,B,A]일 때 dict comprehension이 A의 순번을 마지막 값(2)으로
    덮어써서 B가 A보다 앞으로 오던 버그.
    """
    chunk_a = FakeChunk(section_id="A", chunk_order=1)
    chunk_b = FakeChunk(section_id="B", chunk_order=2)

    ordered = order_chunks_by_requested_sections([chunk_a, chunk_b], ["A", "B", "A"])

    assert [c.section_id for c in ordered] == ["A", "B"]


def test_chunk_missing_from_requested_sections_sorts_last() -> None:
    chunk_a = FakeChunk(section_id="A", chunk_order=1)
    chunk_unknown = FakeChunk(section_id="Z", chunk_order=0)

    ordered = order_chunks_by_requested_sections([chunk_unknown, chunk_a], ["A"])

    assert [c.section_id for c in ordered] == ["A", "Z"]
