"""add rule_review_queue table

Revision ID: 2cc2daabefdc
Revises: b1e9a4c7f052
Create Date: 2026-09-27 15:50:37.703838

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2cc2daabefdc'
down_revision: Union[str, Sequence[str], None] = 'b1e9a4c7f052'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 자동생성이 기존 테이블들의 인덱스 삭제(모델-DB 드리프트, 이 작업과 무관)까지 같이
    # 잡아내서 rule_review_queue 생성만 남기고 나머지는 손으로 제거했다.
    op.create_table(
        'rule_review_queue',
        sa.Column('thread_id', sa.String(), nullable=False),
        sa.Column('document_id', sa.String(), nullable=False),
        sa.Column('items', sa.JSON(), nullable=False),
        sa.Column('chunks', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('decisions', sa.JSON(), nullable=True),
        sa.Column('reviewed_by', sa.String(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('thread_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('rule_review_queue')
