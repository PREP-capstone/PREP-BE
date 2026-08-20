"""add item_code to health_data_items and CHECK constraint on source

Revision ID: e4a1c9b6d3f0
Revises: b9f3a2d6c8e1
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e4a1c9b6d3f0"
down_revision: Union[str, Sequence[str], None] = "b9f3a2d6c8e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("health_data_items", sa.Column("item_code", sa.String(length=80), nullable=True))
    op.create_index("ix_health_data_items_item_code", "health_data_items", ["item_code"])
    op.create_check_constraint(
        "ck_health_data_items_source",
        "health_data_items",
        "source IN ('user_input', 'device_sync', 'os_sync')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_health_data_items_source", "health_data_items", type_="check")
    op.drop_index("ix_health_data_items_item_code", table_name="health_data_items")
    op.drop_column("health_data_items", "item_code")
