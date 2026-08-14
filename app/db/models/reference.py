import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class SignalConfig(Base):
    """signal_config — score axis threshold configuration."""

    __tablename__ = "signal_config"
    __table_args__ = (
        UniqueConstraint("rule_version_id", "axis", name="uq_signal_config_rule_axis"),
    )

    config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rule_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rule_versions.rule_version_id"), nullable=False
    )
    axis: Mapped[str] = mapped_column(String(50), nullable=False)
    threshold_low: Mapped[int] = mapped_column(Integer, nullable=False)
    threshold_mid: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DataDifficulty(Base):
    """data_difficulty — D weight by collected data type."""

    __tablename__ = "data_difficulty"

    data_type: Mapped[str] = mapped_column(String(50), primary_key=True)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CollectionDifficulty(Base):
    """collection_difficulty — S weight by collection method."""

    __tablename__ = "collection_difficulty"

    method: Mapped[str] = mapped_column(String(50), primary_key=True)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
