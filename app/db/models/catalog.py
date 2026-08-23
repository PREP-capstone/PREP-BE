from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class DataSensitivity(Base):
    """data_sensitivity — collected health data sensitivity catalog."""

    __tablename__ = "data_sensitivity"

    item_code: Mapped[str] = mapped_column(String(80), primary_key=True)
    item_label: Mapped[str] = mapped_column(String(120), nullable=False)
    data_type: Mapped[str] = mapped_column(String(50), nullable=False)
    sensitivity_level: Mapped[int] = mapped_column(Integer, nullable=False)
    requires_separate_consent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    legal_basis_doc: Mapped[str | None] = mapped_column(String(160), nullable=True)
    legal_basis_article: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PublicDataCatalog(Base):
    """public_data_catalog — public dataset candidates for data feasibility."""

    __tablename__ = "public_data_catalog"

    dataset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    org: Mapped[str | None] = mapped_column(String(200), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_1_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    access_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    update_cycle: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ApiCatalog(Base):
    """api_catalog — third-party API candidates for data collection."""

    __tablename__ = "api_catalog"

    api_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    available_data_types: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform: Mapped[str | None] = mapped_column(String(120), nullable=True)
    access_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    integration_difficulty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    collection_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ActionTemplate(Base):
    """action_templates — recommendation text emitted by diagnosis triggers."""

    __tablename__ = "action_templates"

    template_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    scope: Mapped[str] = mapped_column(String(80), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(80), nullable=False)
    trigger_value: Mapped[str] = mapped_column(String(120), nullable=False)
    action_text: Mapped[str] = mapped_column(Text, nullable=False)
    ref_doc: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tag: Mapped[str | None] = mapped_column(String(80), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MvpStrategyTemplate(Base):
    """mvp_strategy_templates — MVP roadmap text by category and difficulty."""

    __tablename__ = "mvp_strategy_templates"

    template_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    category_1: Mapped[str | None] = mapped_column(String(80), nullable=True)
    difficulty_level: Mapped[str] = mapped_column(String(30), nullable=False)
    stage: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Competitor(Base):
    """competitors — comparable services used for market and BM analysis."""

    __tablename__ = "competitors"

    competitor_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category_1: Mapped[str | None] = mapped_column(String(80), nullable=True)
    category_2: Mapped[str | None] = mapped_column(String(80), nullable=True)
    country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tier: Mapped[str | None] = mapped_column(String(80), nullable=True)
    data_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target: Mapped[str | None] = mapped_column(String(200), nullable=True)
    service_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    core_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    sub_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    bm_pattern: Mapped[str | None] = mapped_column(String(160), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_created_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_updated_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    limitation: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BmMapping(Base):
    """bm_mapping — aggregated business-model patterns by service segment."""

    __tablename__ = "bm_mapping"

    mapping_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    category_1: Mapped[str | None] = mapped_column(String(80), nullable=True)
    category_2: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target: Mapped[str | None] = mapped_column(String(200), nullable=True)
    service_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bm_pattern: Mapped[str | None] = mapped_column(String(160), nullable=True)
    frequency_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frequency_score_global: Mapped[int | None] = mapped_column(Integer, nullable=True)
    precedent_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    contributing_competitor_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    last_computed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SectionLinkRule(Base):
    """section_link_rules — cross-section navigation hints for the report.

    condition_type/condition_value match against judge_gate() output
    (gate_verdict, data_type) or the session's service_type. 판정엔진_개발설계서.md §15.8.
    """

    __tablename__ = "section_link_rules"

    rule_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    condition_type: Mapped[str] = mapped_column(String(80), nullable=False)
    condition_value: Mapped[str] = mapped_column(String(120), nullable=False)
    target_section: Mapped[str] = mapped_column(String(120), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TrendSignalConfig(Base):
    """trend_signal_config — market trend threshold values from the trend workbook."""

    __tablename__ = "trend_signal_config"

    axis_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(120), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
