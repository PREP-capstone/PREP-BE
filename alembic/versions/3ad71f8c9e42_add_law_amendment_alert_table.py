"""add law_amendment_alert table

Revision ID: 3ad71f8c9e42
Revises: 2cc2daabefdc
Create Date: 2026-09-27 18:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "3ad71f8c9e42"
down_revision: Union[str, Sequence[str], None] = "2cc2daabefdc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "law_amendment_alert",
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("law_title", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=True),
        sa.Column("known_promulgation_no", sa.Integer(), nullable=False),
        sa.Column("latest_promulgation_no", sa.Integer(), nullable=False),
        sa.Column("known_effective_date", sa.String(), nullable=False),
        sa.Column("latest_effective_date", sa.String(), nullable=False),
        sa.Column("changed_articles", sa.JSON(), nullable=False),
        sa.Column("related_articles", sa.JSON(), nullable=False),
        sa.Column("relevance", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("alert_id"),
    )
    # 같은 개정(법령명+공포번호)을 스크립트 돌릴 때마다 중복 생성하지 않기 위한 키.
    op.create_unique_constraint(
        "uq_law_amendment_alert_law_promulgation",
        "law_amendment_alert",
        ["law_title", "latest_promulgation_no"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uq_law_amendment_alert_law_promulgation", "law_amendment_alert", type_="unique"
    )
    op.drop_table("law_amendment_alert")
