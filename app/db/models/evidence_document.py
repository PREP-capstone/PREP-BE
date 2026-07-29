from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class EvidenceDocument(Base):
    """evidence_documents — RAG 근거 문서 metadata."""

    __tablename__ = "evidence_documents"

    document_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    law_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_subtype: Mapped[str | None] = mapped_column(String(50), nullable=True)
    issuing_org: Mapped[str | None] = mapped_column(String(200), nullable=True)
    jurisdiction: Mapped[str] = mapped_column(String(10), nullable=False, default="KR")
    rag_category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    tag_regulatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tag_privacy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tag_advertising: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    usage_scope: Mapped[str] = mapped_column(String(20), nullable=False, default="RAG")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    collection_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    processing_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
