"""LangGraph 파이프라인 State 스키마. """

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
    # retry_extract가 실패한 draft를 어느 청크에서 다시 뽑아야 하는지 알아야 해서 추가.
    # auto_validate는 통과분만 남기고 실패분은 버렸었는데(집계만 남김), 재시도를 하려면
    # "어떤 draft가 어느 청크에서, 왜 실패했는지"가 필요해 실패 draft 자체를 보존하게
    # 바꾸면서 같이 필요해진 필드다(관리자 검수 기능 착수, 2026-09-27).
    source_chunk_id: str


class FailedDraft(TypedDict):
    draft: ExtractedDraft
    reasons: list[str]


class ValidationResult(TypedDict):
    passed: bool
    failed_checks: list[str]  # ["필드누락", "값오류", "인용미확인", "중복후보", "파생값불일치"]
    # 사유별 발생 건수. 사유 목록만으로는 "무엇이 얼마나 걸렀는지"를 알 수 없어
    # 프롬프트를 고칠지 검증을 고칠지 판단할 근거가 없다.
    failed_counts: dict[str, int]
    # 실패한 draft 자체 + 사유(draft별). retry_extract가 어느 청크를 어떤 사유로 다시
    # 추출해야 하는지 알기 위한 원본 데이터 — failed_checks/failed_counts는 집계라
    # 여기엔 draft별 대응이 없다.
    failed_drafts: list[FailedDraft]


class PipelineState(TypedDict):
    source_path: NotRequired[str]  # load_shared_chunks 경로가 붙으면 없을 수도 있음
    document_id: str
    # 정규화 전 원본 제목(한글 파일명/법령명). document_id는 업로드 시점에 kr-* 영문 slug로
    # 정규화되므로(document_id_normalize.py) classify_document_source가 그 값으로는 "시행규칙"
    # 같은 한글 패턴을 찾을 수 없다 — 분류는 반드시 이 원본 제목을 봐야 한다.
    source_title: NotRequired[str]
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
    # admin_decision/reject_reason(단수)는 설계서 초안이 draft 1건씩 검수하던 시절 필드다.
    # 2026-09-27 배치 단위 검수로 확정하면서 승인/반려가 draft별로 섞여 나올 수 있어 단일
    # Literal로 못 담는다 — reject_log가 쓸 반려 목록만 별도로 둔다. drafts는 human_review가
    # 승인분으로 이미 덮어써서 publish로 그대로 넘어간다.
    rejected_drafts: list[dict]  # [{"draft": ExtractedDraft, "reason": str | None}]
