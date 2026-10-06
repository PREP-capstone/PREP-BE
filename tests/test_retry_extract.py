"""retry_extract 회귀 테스트 — 실패 사유가 프롬프트에 실제로 첨부되는지, retry_count가
올라가는지, 재추출 방법이 없는(Stage D 등) draft는 버려지지 않고 그대로 실리는지 확인한다.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.pipeline.nodes.retry_extract import retry_extract

@pytest.fixture(autouse=True)
def _no_openai_client():
    """실제 AsyncOpenAI 생성을 막는다 — 키가 없는 CI에서는 생성 자체가 예외다."""
    with patch("app.pipeline.nodes.retry_extract._build_client", return_value=None):
        yield


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


async def test_retry_extract_carries_forward_when_reextraction_returns_nothing() -> None:
    """재추출이 0건을 반환해도 원본 draft가 사라지면 안 된다.

    프롬프트가 "관련 키워드가 없으면 빈 배열"을 명시적으로 허용해서(extract_a.py) 실제로
    자주 일어날 수 있는 경로다. auto_validate가 실패 draft를 이미 drafts에서 빼둔 상태라
    여기서 안 실으면 human_review 큐에도 안 올라가고 그대로 폐기된다.
    """
    failed = [_failed_entry("A", "chunk-1", ["인용미확인"])]
    state = _state(validation={"passed": False, "failed_checks": [], "failed_counts": {}, "failed_drafts": failed})

    with patch("app.pipeline.nodes.retry_extract.extract_chunk_A", new=AsyncMock(return_value=[])):
        result = await retry_extract(state)

    assert len(result["drafts"]) == 1, "재추출이 빈 배열을 줬으면 원본 draft를 다시 실어야 한다"
    assert result["drafts"][0]["stage"] == "A"


async def test_retry_extract_replaces_original_when_reextraction_succeeds() -> None:
    """재추출이 결과를 내면 원본은 실지 않는다 — 둘 다 실으면 중복후보로 걸린다."""
    failed = [_failed_entry("A", "chunk-1", ["인용미확인"])]
    state = _state(validation={"passed": False, "failed_checks": [], "failed_counts": {}, "failed_drafts": failed})
    retried = {"stage": "A", "fields": {"keyword": "재추출됨"}, "legal_basis": {}, "source_chunk_id": "chunk-1"}

    with patch(
        "app.pipeline.nodes.retry_extract.extract_chunk_A", new=AsyncMock(return_value=[retried])
    ):
        result = await retry_extract(state)

    assert result["drafts"] == [retried]


async def test_retry_extract_drops_reextracted_copy_of_already_passed_draft() -> None:
    """청크를 통째로 다시 뽑으면 이미 통과한 draft도 같이 나온다 — 그대로 실으면 다음
    auto_validate에서 중복후보로 걸려 재시도가 수렴하지 않는다."""
    passed = {"stage": "A", "fields": {"keyword": "통과"}, "legal_basis": {}, "source_chunk_id": "chunk-1"}
    fixed = {"stage": "A", "fields": {"keyword": "고침"}, "legal_basis": {}, "source_chunk_id": "chunk-1"}
    failed = [_failed_entry("A", "chunk-1", ["인용미확인"])]
    state = _state(
        drafts=[passed],
        validation={"passed": False, "failed_checks": [], "failed_counts": {}, "failed_drafts": failed},
    )

    with patch(
        "app.pipeline.nodes.retry_extract.extract_chunk_A",
        new=AsyncMock(return_value=[dict(passed), fixed]),
    ):
        result = await retry_extract(state)

    assert result["drafts"] == [passed, fixed]


async def test_retry_extract_skips_llm_for_duplicate_only_failures() -> None:
    """중복후보는 다시 뽑아도 똑같이 걸린다 — LLM을 부르지 않고 그대로 검수로 넘긴다."""
    failed = [_failed_entry("A", "chunk-1", ["중복후보"])]
    state = _state(validation={"passed": False, "failed_checks": [], "failed_counts": {}, "failed_drafts": failed})

    with patch(
        "app.pipeline.nodes.retry_extract.extract_chunk_A", new=AsyncMock(return_value=[])
    ) as mock_extract:
        result = await retry_extract(state)

    mock_extract.assert_not_called()
    assert result["drafts"] == [failed[0]["draft"]]


def test_route_skips_retry_when_only_duplicates_failed() -> None:
    from app.pipeline.graph import _route_after_validate

    def _routed(reasons: list[str]) -> str:
        return _route_after_validate(
            {"retry_count": 0, "validation": {"passed": False, "failed_drafts": [_failed_entry("A", "chunk-1", reasons)]}}
        )

    assert _routed(["중복후보"]) == "human_review"
    assert _routed(["중복후보", "인용미확인"]) == "retry_extract"


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
