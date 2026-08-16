"""add verb_substitution table

Revision ID: 7679f09d3c04
Revises: d72baa5ee860
Create Date: 2026-08-13 21:56:49.767106

data_difficulty·collection_difficulty와 같은 고정 기준표 패턴 — LLM 추출 대상이
아니라 직접 INSERT하고 rule_version에 묶지 않는다.

autogenerate가 매번 잡아내는 evidence_chunks/evidence_documents 인덱스 9개 drop은
오탐이라 제거했다(RAG 담당 모델에 인덱스가 SQLAlchemy 선언 없이 존재해서 발생).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7679f09d3c04'
down_revision: Union[str, Sequence[str], None] = 'd72baa5ee860'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('verb_substitution',
    sa.Column('verb', sa.String(), nullable=False),
    sa.Column('verb_category', sa.String(), nullable=False),
    sa.Column('safe_verb', sa.String(), nullable=False),
    sa.Column('noun_classes', sa.String(), nullable=False),
    sa.Column('standalone', sa.Boolean(), nullable=False),
    sa.Column('legal_basis_doc', sa.String(), nullable=True),
    sa.Column('legal_basis_article', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('verb')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('verb_substitution')
