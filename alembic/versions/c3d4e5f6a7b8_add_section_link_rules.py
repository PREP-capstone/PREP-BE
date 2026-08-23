"""add section_link_rules table

Revision ID: c3d4e5f6a7b8
Revises: a1b2c3d4e5f6
Create Date: 2026-08-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "section_link_rules",
        sa.Column("rule_id", sa.String(length=80), nullable=False),
        sa.Column("condition_type", sa.String(length=80), nullable=False),
        sa.Column("condition_value", sa.String(length=120), nullable=False),
        sa.Column("target_section", sa.String(length=120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("rule_id"),
    )
    op.create_index(
        "ix_section_link_rules_condition",
        "section_link_rules",
        ["condition_type", "condition_value"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_section_link_rules_condition", table_name="section_link_rules")
    op.drop_table("section_link_rules")
