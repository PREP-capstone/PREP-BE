"""merge rulebase and postgres catalog migration heads

Revision ID: a8c7f6e5d4b3
Revises: 7679f09d3c04, f1c2d3e4a5b6
Create Date: 2026-08-16 00:00:00.000000

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "a8c7f6e5d4b3"
down_revision: Union[str, Sequence[str], None] = ("7679f09d3c04", "f1c2d3e4a5b6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge migration branches; no schema changes."""


def downgrade() -> None:
    """Unmerge migration branches; no schema changes."""
