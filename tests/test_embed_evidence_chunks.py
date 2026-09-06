from scripts.embed_evidence_chunks import (
    EMBEDDING_PART_SEPARATOR,
    MAX_EMBEDDING_TEXT_CHARS,
    split_embedding_parts,
    split_text_for_embedding,
)


def test_split_text_for_embedding_keeps_short_text_as_single_part() -> None:
    text = "짧은 조문입니다."

    assert split_text_for_embedding(text) == [text]


def test_split_embedding_parts_uses_stable_part_ids_for_long_text() -> None:
    row = {
        "chunk_id": "kr-test-guide__II",
        "chunk_text": "가" * (MAX_EMBEDDING_TEXT_CHARS + 10),
    }

    parts = split_embedding_parts(row)

    assert len(parts) == 2
    assert parts[0]["chunk_id"] == f"kr-test-guide__II{EMBEDDING_PART_SEPARATOR}1"
    assert parts[1]["chunk_id"] == f"kr-test-guide__II{EMBEDDING_PART_SEPARATOR}2"
    assert all(len(part["chunk_text"]) <= MAX_EMBEDDING_TEXT_CHARS for part in parts)
    assert {part["parent_chunk_id"] for part in parts} == {"kr-test-guide__II"}
    assert [part["chunk_part_index"] for part in parts] == [1, 2]
    assert {part["chunk_part_count"] for part in parts} == {2}
