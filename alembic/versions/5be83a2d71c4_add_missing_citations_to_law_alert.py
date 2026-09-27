"""add missing_citations to law_amendment_alert

Revision ID: 5be83a2d71c4
Revises: 3ad71f8c9e42
Create Date: 2026-09-27 18:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5be83a2d71c4"
down_revision: Union[str, Sequence[str], None] = "3ad71f8c9e42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 우리 룰이 인용하는 조문 중 현행 법령에서 사라진 것 — 조문이 삭제되면 그 룰은
    # legal_basis_article 조인 키가 깨져 근거를 못 찾는다(app/domain/law_amendment.py).
    op.add_column(
        "law_amendment_alert",
        sa.Column("missing_citations", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("law_amendment_alert", "missing_citations")
