"""LangGraph 파이프라인 State 스키마. 현재는 Stage A만 구현해 current_stage/target_stages는
단일값("A")으로만 쓰고, Send 팬아웃이 붙으면 target_stages가 복수 Stage를 담게 된다.
"""

from typing import Literal, NotRequired, Optional, TypedDict


class Chunk(TypedDict):
    chunk_id: str
    document_id: str
    article_number: str  # 예: "Ⅲ.2.가"
    section_path: str
    content: str
    source: Literal["own", "shared_rag"]


class ExtractedDraft(TypedDict):
    stage: Literal["A", "B", "C", "D"]
    fields: dict  # Stage별 추출 스키마
    legal_basis: dict  # {"document_id", "article", "quote"}


class ValidationResult(TypedDict):
    passed: bool
    failed_checks: list[str]  # ["필드누락", "값오류", "인용미확인", "중복후보", "파생값불일치"]


class PipelineState(TypedDict):
    source_path: NotRequired[str]  # load_shared_chunks 경로가 붙으면 없을 수도 있음
    document_id: str
    document_category: Literal["법령규제문서", "판단가이드", "위험표현사전"]
    raw_text: str
    chunks: list[Chunk]
    current_chunk_id: Optional[str]
    current_stage: Optional[Literal["A", "B", "C", "D"]]
    target_stages: list[Literal["A", "B", "C", "D"]]
    drafts: list[ExtractedDraft]
    derived_values: dict  # Stage C 전용
    validation: Optional[ValidationResult]
    retry_count: int
    rule_version_id: Optional[str]
    admin_decision: Optional[Literal["approve", "reject"]]
    reject_reason: Optional[str]
