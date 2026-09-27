"""retry_extract 회귀 테스트 — 실패 사유가 프롬프트에 실제로 첨부되는지, retry_count가
올라가는지, 재추출 방법이 없는(Stage D 등) draft는 버려지지 않고 그대로 실리는지 확인한다.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.pipeline.nodes.retry_extract import retry_extract

CHUNK = {
    "chunk_id": "chunk-1",
    "document_id": "doc-1",
    "article_number": "제1조",
    "section_path": "제1조",
    "content": "테스트 조문",
    "source": "own",
}


def _failed_entry(stage: str, chunk_id: str, reasons: list[str]) -> dict:
    return {
        "draft": {
            "stage": stage,
            "fields": {"keyword": "테스트"},
            "legal_basis": {},
            "source_chunk_id": chunk_id,
        },
        "reasons": reasons,
    }


def _state(**overrides) -> dict:
    base = {
        "document_id": "doc-1",
        "chunks": [CHUNK],
        "drafts": [],
        "validation": {"passed": False, "failed_checks": [], "failed_counts": {}, "failed_drafts": []},
        "retry_count": 0,
    }
    base.update(overrides)
    return base


async def test_retry_extract_passes_failure_reason_to_prompt() -> None:
    failed = [_failed_entry("A", "chunk-1", ["필드누락"])]
    state = _state(validation={"passed": False, "failed_checks": [], "failed_counts": {}, "failed_drafts": failed})

    with patch(
        "app.pipeline.nodes.retry_extract.extract_chunk_A", new=AsyncMock(return_value=[])
    ) as mock_extract:
        result = await retry_extract(state)

    mock_extract.assert_called_once()
    args, _ = mock_extract.call_args
    extra_context = args[3]
    assert "필드누락" in extra_context
    assert result["retry_count"] == 1


async def test_retry_extract_carries_forward_undretryable_draft() -> None:
    """Stage D처럼 재추출 헬퍼가 없는 실패 draft는 버리지 않고 그대로 다시 실어야
    다음 auto_validate에서도 사라지지 않고 결국 human_review까지 도달한다."""
    failed = [_failed_entry("D", "chunk-1", ["값오류"])]
    state = _state(validation={"passed": False, "failed_checks": [], "failed_counts": {}, "failed_drafts": failed})

    result = await retry_extract(state)

    assert len(result["drafts"]) == 1
    assert result["drafts"][0]["stage"] == "D"
    assert result["retry_count"] == 1


async def test_retry_extract_groups_multiple_failures_from_same_chunk() -> None:
    """같은 청크에서 실패한 draft가 여러 개면 재추출 호출은 한 번만(청크당 1회) 일어나야
    한다 — draft마다 따로 부르면 같은 청크를 중복으로 재추출하게 된다."""
    failed = [
        _failed_entry("A", "chunk-1", ["필드누락"]),
        _failed_entry("A", "chunk-1", ["값오류"]),
    ]
    state = _state(validation={"passed": False, "failed_checks": [], "failed_counts": {}, "failed_drafts": failed})

    with patch(
        "app.pipeline.nodes.retry_extract.extract_chunk_A", new=AsyncMock(return_value=[])
    ) as mock_extract:
        await retry_extract(state)

    assert mock_extract.call_count == 1
    extra_context = mock_extract.call_args.args[3]
    assert "필드누락" in extra_context
    assert "값오류" in extra_context
