from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class AnalysisSession(Base):
    """analysis_sessions — 아이디어 검진 1회 입력 세션."""

    __tablename__ = "analysis_sessions"

    session_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    service_name: Mapped[str] = mapped_column(String(200), nullable=False)
    service_description: Mapped[str] = mapped_column(Text, nullable=False)
    target_users: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    service_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    processing_purpose: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    service_actions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class HealthDataItem(Base):
    """health_data_items — 분석 세션이 입력받거나 처리하는 건강/검진 데이터.

    SQLAlchemy ORM 모델이다. FastAPI 요청/응답 바디로는 이 클래스를 쓰지 말고
    app.schemas.common.HealthDataItemInput(Pydantic)을 써야 한다 — 이름이 같아
    헷갈리기 쉬운데, ORM 모델을 request body 타입으로 잘못 넣으면 FastAPI가 스키마를
    생성하지 못해 앱 기동 자체가 깨진다.
    """

    __tablename__ = "health_data_items"

    health_data_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("analysis_sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    data_type: Mapped[str] = mapped_column(String(50), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    item_code: Mapped[str | None] = mapped_column(String(80), nullable=True)  # data_sensitivity.item_code
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
