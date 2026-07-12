"""LangGraph 파이프라인 State 스키마.

참고: docs/langgraph_파이프라인_설계서.md §3
현재는 Stage A만 구현하므로 current_stage/target_stages는 단일값("A")으로만 채워 쓴다.
Stage B/C/D, Send 팬아웃이 붙으면 target_stages가 복수 Stage를 담게 된다.
"""

from typing import Literal, NotRequired, Optional, TypedDict


class Chunk(TypedDict):
    chunk_id: str
    document_id: str
    article_number: str  # 예: "Ⅲ.2.가" — RAG(evidence_chunks)와 표기 규칙 공유 필요(설계서 §13)
    section_path: str
    content: str
    source: Literal["own", "shared_rag"]  # 직접 청킹했는지, 팀원 RAG의 evidence_chunks를 재사용했는지


class ExtractedDraft(TypedDict):
    stage: Literal["A", "B", "C", "D"]
    fields: dict  # Stage별 추출 스키마 (db_구축_설계서.md §4.2 JSON)
    legal_basis: dict  # {"document_id", "article", "quote"}


class ValidationResult(TypedDict):
    passed: bool
    failed_checks: list[str]  # ["필드누락", "값오류", "인용미확인", "중복후보", "파생값불일치"]


class PipelineState(TypedDict):
    # 설계서 §3에는 없으나 ingest_document의 실제 입력(PDF 경로)이 필요해 추가.
    # NotRequired: classify_document_source/load_shared_chunks(§2, §5.0)가 붙으면 법령·규제 문서는
    # PDF를 직접 안 받고 RAG의 evidence_chunks를 재사용하므로 이 키 자체가 안 들어오는 경우가 생긴다.
    source_path: NotRequired[str]
    document_id: str
    document_category: Literal["법령규제문서", "판단가이드", "위험표현사전"]
    raw_text: str
    chunks: list[Chunk]
    current_chunk_id: Optional[str]
    current_stage: Optional[Literal["A", "B", "C", "D"]]  # TODO(Send): route_stage 도입 시 팬아웃마다 세팅
    target_stages: list[Literal["A", "B", "C", "D"]]
    drafts: list[ExtractedDraft]
    derived_values: dict  # Stage C 전용: {"regulatory_score":, "privacy_score":, "derived_from_keyword_id":}
    validation: Optional[ValidationResult]
    retry_count: int
    rule_version_id: Optional[str]
    admin_decision: Optional[Literal["approve", "reject"]]
    reject_reason: Optional[str]
