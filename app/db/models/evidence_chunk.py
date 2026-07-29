from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class EvidenceChunk(Base):
    """evidence_chunks — RAG 검색 및 근거 표시용 chunk metadata."""

    __tablename__ = "evidence_chunks"

    chunk_id: Mapped[str] = mapped_column(String(220), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(160), ForeignKey("evidence_documents.document_id"), nullable=False
    )
    chunk_order: Mapped[int] = mapped_column(Integer, nullable=False)
    section_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    chunk_type: Mapped[str] = mapped_column(String(40), nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tag_regulatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tag_privacy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tag_advertising: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    case_tag_advertising: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    case_tag_privacy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    case_tag_medical_device: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    case_tag_health_functional_food: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
