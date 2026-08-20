"""add analysis sessions and health data items

Revision ID: b9f3a2d6c8e1
Revises: a8c7f6e5d4b3
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b9f3a2d6c8e1"
down_revision: Union[str, Sequence[str], None] = "a8c7f6e5d4b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "analysis_sessions",
        sa.Column("session_id", sa.String(length=80), nullable=False),
        sa.Column("service_name", sa.String(length=200), nullable=False),
        sa.Column("service_description", sa.Text(), nullable=False),
        sa.Column("target_users", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("service_type", sa.String(length=50), nullable=True),
        sa.Column("processing_purpose", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("service_actions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index("ix_analysis_sessions_created_at", "analysis_sessions", ["created_at"])
    op.create_index("ix_analysis_sessions_service_type", "analysis_sessions", ["service_type"])

    op.create_table(
        "health_data_items",
        sa.Column("health_data_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("data_type", sa.String(length=50), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("is_sensitive", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["analysis_sessions.session_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("health_data_item_id"),
    )
    op.create_index("ix_health_data_items_session_id", "health_data_items", ["session_id"])
    op.create_index("ix_health_data_items_name", "health_data_items", ["name"])
    op.create_index("ix_health_data_items_source", "health_data_items", ["source"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_health_data_items_source", table_name="health_data_items")
    op.drop_index("ix_health_data_items_name", table_name="health_data_items")
    op.drop_index("ix_health_data_items_session_id", table_name="health_data_items")
    op.drop_table("health_data_items")

    op.drop_index("ix_analysis_sessions_service_type", table_name="analysis_sessions")
    op.drop_index("ix_analysis_sessions_created_at", table_name="analysis_sessions")
    op.drop_table("analysis_sessions")
