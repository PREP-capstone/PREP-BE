import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class CorrectionRule(Base):
    """correction_rules — 위험표현·교정 (Stage C). db_구축_설계서.md §3.3"""

    __tablename__ = "correction_rules"

    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_versions.rule_version_id"), nullable=False
    )
    risky_text: Mapped[str] = mapped_column(String, nullable=False)
    safe_text: Mapped[str] = mapped_column(String, nullable=False)
    regulatory_score: Mapped[int] = mapped_column(Integer, nullable=False)
    # privacy_score는 2026-07-28 결정으로 삭제됨 — 값이 룰이 아니라 사용자가 선택한 수집 항목에서
    # 결정되므로 런타임(판정엔진)이 계산한다. db_구축_설계서.md §3.3.2
    advertising_score: Mapped[int] = mapped_column(Integer, nullable=False)
    derived_from_keyword_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gate_keywords.keyword_id"), nullable=True
    )
    legal_basis_doc: Mapped[str] = mapped_column(String, nullable=False)
    legal_basis_article: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
