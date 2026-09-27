import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class RuleReviewQueue(Base):
    """rule_review_queue — human_review 노드가 interrupt() 직전에 써두는 검수 대기 항목.

    LangGraph 체크포인터(Postgres)가 그래프 실행 상태 자체는 이미 영속화하지만, 그 내부를
    admin API가 직접 조회하기엔 불편해서(체크포인터는 조회용 API가 아니다) 목록/상세 화면용으로
    이 얇은 테이블을 따로 둔다. 단일 진실 공급원은 아니고, 그래프 재개(Command(resume=...))의
    키인 thread_id로 체크포인터와 연결된다.

    human_review 노드는 resume될 때마다(=interrupt() 이전 코드가 재실행될 때마다) 이 행을
    다시 쓸 수 있어 PK(thread_id) upsert로 멱등하게 처리한다.
    """

    __tablename__ = "rule_review_queue"

    thread_id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False)
    # 배치 단위 검수(2026-09-27 결정) — 이 문서 실행에서 나온 draft 전체 + 각각의
    # 자동검증 통과/실패 여부·사유를 한 번에 담는다. [{"draft":..., "status":..., "reasons":[...]}]
    items: Mapped[list] = mapped_column(JSON, nullable=False)
    # 검수 화면 좌측 "원문 청크" 표시용 스냅샷. own 청크(app/pipeline/nodes/chunk.py)는
    # RAG의 evidence_chunks와 달리 별도 테이블에 저장되지 않고 그래프 실행 중에만 존재해서,
    # 체크포인터 내부를 admin API가 직접 뒤지게 하는 대신 여기 그대로 복사해 둔다.
    chunks: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")  # pending / resolved
    # 승인/반려 결정이 나온 뒤 채워짐. [{"index":, "action":, "reason":, "edited_fields":}]
    decisions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
