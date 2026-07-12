import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class GateKeyword(Base):
    """gate_keywords — 1차 키워드 스캔 (Stage A). db_구축_설계서.md §3.2"""

    __tablename__ = "gate_keywords"

    keyword_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_versions.rule_version_id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String, nullable=False)  # DISEASE / PROHIBITED_ACTION / DOCTOR_REPLACEMENT
    keyword: Mapped[str] = mapped_column(String, nullable=False)
    keyword_category: Mapped[str] = mapped_column(String, nullable=False)  # DIAGNOSIS / TREATMENT / DATA_TYPE / OTHER
    data_type_focus: Mapped[str] = mapped_column(String, nullable=False)  # IMAGING / NUMERIC / TEXT / LIFESTYLE / NONE
    verdict: Mapped[str] = mapped_column(String, nullable=False)  # FAIL_CANDIDATE / CONTEXT_CHECK / FAIL_CONFIRMED
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
