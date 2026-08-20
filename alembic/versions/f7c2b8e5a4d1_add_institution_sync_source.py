"""expand health_data_items.source CHECK to include institution_sync

Revision ID: f7c2b8e5a4d1
Revises: e4a1c9b6d3f0
Create Date: 2026-08-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f7c2b8e5a4d1"
down_revision: Union[str, Sequence[str], None] = "e4a1c9b6d3f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("ck_health_data_items_source", "health_data_items", type_="check")
    op.create_check_constraint(
        "ck_health_data_items_source",
        "health_data_items",
        "source IN ('user_input', 'device_sync', 'os_sync', 'institution_sync')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_health_data_items_source", "health_data_items", type_="check")
    op.create_check_constraint(
        "ck_health_data_items_source",
        "health_data_items",
        "source IN ('user_input', 'device_sync', 'os_sync')",
    )
