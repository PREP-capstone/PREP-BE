"""add signal_config, data_difficulty, collection_difficulty tables

Revision ID: d72baa5ee860
Revises: 949b797ffa24
Create Date: 2026-08-09 17:26:11.402118

세 테이블 모두 소비 주체는 판정엔진(런타임)이다 — 오프라인 파이프라인은 구축·시딩만 한다.
db_구축_설계서.md §3.3.1(signal_config) · §3.4(D×S 점수표)

949b797ffa24와 마찬가지로 autogenerate가 잡은 evidence_* 인덱스 drop은 오탐이라 제거했다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd72baa5ee860'
down_revision: Union[str, Sequence[str], None] = '949b797ffa24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'collection_difficulty',
        sa.Column('method', sa.String(), nullable=False),
        sa.Column('weight', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('method'),
    )
    op.create_table(
        'data_difficulty',
        sa.Column('data_type', sa.String(), nullable=False),
        sa.Column('weight', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('data_type'),
    )
    op.create_table(
        'signal_config',
        sa.Column('config_id', sa.UUID(), nullable=False),
        sa.Column('rule_version_id', sa.UUID(), nullable=False),
        sa.Column('axis', sa.String(), nullable=False),
        sa.Column('threshold_low', sa.Integer(), nullable=False),
        sa.Column('threshold_mid', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['rule_version_id'], ['rule_versions.rule_version_id'], ),
        sa.PrimaryKeyConstraint('config_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('signal_config')
    op.drop_table('data_difficulty')
    op.drop_table('collection_difficulty')
