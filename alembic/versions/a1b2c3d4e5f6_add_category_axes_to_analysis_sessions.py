"""add category_1/category_2/target to analysis_sessions

Revision ID: a1b2c3d4e5f6
Revises: f7c2b8e5a4d1
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f7c2b8e5a4d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("analysis_sessions", sa.Column("category_1", sa.String(length=80), nullable=True))
    op.add_column("analysis_sessions", sa.Column("category_2", sa.String(length=80), nullable=True))
    op.add_column("analysis_sessions", sa.Column("target", sa.String(length=200), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("analysis_sessions", "target")
    op.drop_column("analysis_sessions", "category_2")
    op.drop_column("analysis_sessions", "category_1")
