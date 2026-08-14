"""add reference seed tables

Revision ID: e4b2a1c9d8f0
Revises: d7a8c2f1b934
Create Date: 2026-08-15 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4b2a1c9d8f0"
down_revision: Union[str, Sequence[str], None] = "d7a8c2f1b934"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "signal_config",
        sa.Column("config_id", sa.UUID(), nullable=False),
        sa.Column("rule_version_id", sa.UUID(), nullable=False),
        sa.Column("axis", sa.String(length=50), nullable=False),
        sa.Column("threshold_low", sa.Integer(), nullable=False),
        sa.Column("threshold_mid", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["rule_version_id"], ["rule_versions.rule_version_id"]),
        sa.PrimaryKeyConstraint("config_id"),
        sa.UniqueConstraint("rule_version_id", "axis", name="uq_signal_config_rule_axis"),
    )
    op.create_index("ix_signal_config_rule_version_id", "signal_config", ["rule_version_id"])

    op.create_table(
        "data_difficulty",
        sa.Column("data_type", sa.String(length=50), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("data_type"),
    )

    op.create_table(
        "collection_difficulty",
        sa.Column("method", sa.String(length=50), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("method"),
    )


def downgrade() -> None:
    op.drop_table("collection_difficulty")
    op.drop_table("data_difficulty")
    op.drop_index("ix_signal_config_rule_version_id", table_name="signal_config")
    op.drop_table("signal_config")
