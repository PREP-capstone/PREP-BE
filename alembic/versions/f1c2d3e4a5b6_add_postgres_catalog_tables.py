"""add postgres catalog seed tables

Revision ID: f1c2d3e4a5b6
Revises: e4b2a1c9d8f0
Create Date: 2026-08-15 02:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f1c2d3e4a5b6"
down_revision: Union[str, Sequence[str], None] = "e4b2a1c9d8f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "data_sensitivity",
        sa.Column("item_code", sa.String(length=80), nullable=False),
        sa.Column("item_label", sa.String(length=120), nullable=False),
        sa.Column("data_type", sa.String(length=50), nullable=False),
        sa.Column("sensitivity_level", sa.Integer(), nullable=False),
        sa.Column("requires_separate_consent", sa.Boolean(), nullable=False),
        sa.Column("legal_basis_doc", sa.String(length=160), nullable=True),
        sa.Column("legal_basis_article", sa.String(length=200), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("item_code"),
    )
    op.create_index("ix_data_sensitivity_data_type", "data_sensitivity", ["data_type"])
    op.create_index(
        "ix_data_sensitivity_sensitivity_level",
        "data_sensitivity",
        ["sensitivity_level"],
    )

    op.create_table(
        "public_data_catalog",
        sa.Column("dataset_id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("org", sa.String(length=200), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("category_1_tags", sa.Text(), nullable=True),
        sa.Column("data_type", sa.String(length=50), nullable=True),
        sa.Column("access_type", sa.String(length=80), nullable=True),
        sa.Column("difficulty", sa.Integer(), nullable=True),
        sa.Column("update_cycle", sa.String(length=120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("dataset_id"),
    )
    op.create_index("ix_public_data_catalog_data_type", "public_data_catalog", ["data_type"])
    op.create_index("ix_public_data_catalog_difficulty", "public_data_catalog", ["difficulty"])

    op.create_table(
        "api_catalog",
        sa.Column("api_id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("available_data_types", sa.Text(), nullable=True),
        sa.Column("platform", sa.String(length=120), nullable=True),
        sa.Column("access_type", sa.String(length=120), nullable=True),
        sa.Column("integration_difficulty", sa.Integer(), nullable=True),
        sa.Column("collection_method", sa.String(length=100), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("api_id"),
    )
    op.create_index("ix_api_catalog_provider", "api_catalog", ["provider"])
    op.create_index(
        "ix_api_catalog_integration_difficulty",
        "api_catalog",
        ["integration_difficulty"],
    )

    op.create_table(
        "action_templates",
        sa.Column("template_id", sa.String(length=100), nullable=False),
        sa.Column("scope", sa.String(length=80), nullable=False),
        sa.Column("trigger_type", sa.String(length=80), nullable=False),
        sa.Column("trigger_value", sa.String(length=120), nullable=False),
        sa.Column("action_text", sa.Text(), nullable=False),
        sa.Column("ref_doc", sa.String(length=200), nullable=True),
        sa.Column("tag", sa.String(length=80), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("template_id"),
    )
    op.create_index("ix_action_templates_trigger", "action_templates", ["trigger_type", "trigger_value"])
    op.create_index("ix_action_templates_priority", "action_templates", ["priority"])

    op.create_table(
        "mvp_strategy_templates",
        sa.Column("template_id", sa.String(length=100), nullable=False),
        sa.Column("category_1", sa.String(length=80), nullable=True),
        sa.Column("difficulty_level", sa.String(length=30), nullable=False),
        sa.Column("stage", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("template_id"),
    )
    op.create_index(
        "ix_mvp_strategy_templates_lookup",
        "mvp_strategy_templates",
        ["category_1", "difficulty_level"],
    )

    op.create_table(
        "competitors",
        sa.Column("competitor_id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category_1", sa.String(length=80), nullable=True),
        sa.Column("category_2", sa.String(length=80), nullable=True),
        sa.Column("country", sa.String(length=80), nullable=True),
        sa.Column("tier", sa.String(length=80), nullable=True),
        sa.Column("data_type", sa.String(length=80), nullable=True),
        sa.Column("target", sa.String(length=200), nullable=True),
        sa.Column("service_type", sa.String(length=120), nullable=True),
        sa.Column("core_tags", sa.Text(), nullable=True),
        sa.Column("sub_tags", sa.Text(), nullable=True),
        sa.Column("bm_pattern", sa.String(length=160), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source_created_at", sa.Date(), nullable=True),
        sa.Column("source_updated_at", sa.Date(), nullable=True),
        sa.Column("limitation", sa.Text(), nullable=True),
        sa.Column("price", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("competitor_id"),
    )
    op.create_index("ix_competitors_category", "competitors", ["category_1", "category_2"])
    op.create_index("ix_competitors_tier", "competitors", ["tier"])
    op.create_index("ix_competitors_service_type", "competitors", ["service_type"])

    op.create_table(
        "bm_mapping",
        sa.Column("mapping_id", sa.String(length=80), nullable=False),
        sa.Column("category_1", sa.String(length=80), nullable=True),
        sa.Column("category_2", sa.String(length=80), nullable=True),
        sa.Column("target", sa.String(length=200), nullable=True),
        sa.Column("service_type", sa.String(length=120), nullable=True),
        sa.Column("bm_pattern", sa.String(length=160), nullable=True),
        sa.Column("frequency_score", sa.Integer(), nullable=True),
        sa.Column("frequency_score_global", sa.Integer(), nullable=True),
        sa.Column("precedent_level", sa.String(length=50), nullable=True),
        sa.Column("contributing_competitor_ids", sa.Text(), nullable=True),
        sa.Column("evidence_id", sa.String(length=160), nullable=True),
        sa.Column("last_computed_at", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("mapping_id"),
    )
    op.create_index("ix_bm_mapping_lookup", "bm_mapping", ["category_1", "category_2"])

    op.create_table(
        "trend_signal_config",
        sa.Column("axis_key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.String(length=120), nullable=False),
        sa.Column("unit", sa.String(length=200), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("axis_key"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("trend_signal_config")

    op.drop_index("ix_bm_mapping_lookup", table_name="bm_mapping")
    op.drop_table("bm_mapping")

    op.drop_index("ix_competitors_service_type", table_name="competitors")
    op.drop_index("ix_competitors_tier", table_name="competitors")
    op.drop_index("ix_competitors_category", table_name="competitors")
    op.drop_table("competitors")

    op.drop_index("ix_mvp_strategy_templates_lookup", table_name="mvp_strategy_templates")
    op.drop_table("mvp_strategy_templates")

    op.drop_index("ix_action_templates_priority", table_name="action_templates")
    op.drop_index("ix_action_templates_trigger", table_name="action_templates")
    op.drop_table("action_templates")

    op.drop_index("ix_api_catalog_integration_difficulty", table_name="api_catalog")
    op.drop_index("ix_api_catalog_provider", table_name="api_catalog")
    op.drop_table("api_catalog")

    op.drop_index("ix_public_data_catalog_difficulty", table_name="public_data_catalog")
    op.drop_index("ix_public_data_catalog_data_type", table_name="public_data_catalog")
    op.drop_table("public_data_catalog")

    op.drop_index("ix_data_sensitivity_sensitivity_level", table_name="data_sensitivity")
    op.drop_index("ix_data_sensitivity_data_type", table_name="data_sensitivity")
    op.drop_table("data_sensitivity")
