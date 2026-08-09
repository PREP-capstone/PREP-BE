"""add gate_matrix acquire_method/avoidance/legal_basis, drop correction_rules privacy_score

Revision ID: 949b797ffa24
Revises: d7a8c2f1b934
Create Date: 2026-08-09 17:22:33.316651

gate_matrix 컬럼 추가(db_구축_설계서.md §3.2)와 correction_rules.privacy_score 삭제(§3.3.2,
2026-07-28 런타임 이관 결정)를 한 리비전으로 묶는다 — 둘 다 "3축 점수 계산 위치 분리" 결정의
결과물이라 롤백 단위가 같아야 한다.

autogenerate가 evidence_chunks/evidence_documents의 인덱스 9개를 drop 대상으로 잡았으나 전부 제거했다.
해당 인덱스는 d7a8c2f1b934에서 실제로 생성됐지만 모델(app/db/models/evidence_*.py)에는 선언돼 있지 않아
autogenerate가 "모델에 없음 = 삭제됨"으로 오판한 것이다. RAG 담당 스코프이므로 건드리지 않는다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '949b797ffa24'
down_revision: Union[str, Sequence[str], None] = 'd7a8c2f1b934'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('gate_matrix', sa.Column('acquire_method', sa.String(), nullable=True))
    op.add_column('gate_matrix', sa.Column('avoidance_redesign', sa.String(), nullable=True))
    op.add_column('gate_matrix', sa.Column('avoidance_certification', sa.String(), nullable=True))
    op.add_column('gate_matrix', sa.Column('legal_basis_doc', sa.String(), nullable=True))
    op.add_column('gate_matrix', sa.Column('legal_basis_article', sa.String(), nullable=True))
    op.drop_column('correction_rules', 'privacy_score')


def downgrade() -> None:
    """Downgrade schema."""
    # 롤백 시점에 기존 row가 있으면 NOT NULL을 즉시 걸 수 없으므로 server_default로 채운 뒤 해제한다.
    op.add_column(
        'correction_rules',
        sa.Column('privacy_score', sa.INTEGER(), nullable=False, server_default='0'),
    )
    op.alter_column('correction_rules', 'privacy_score', server_default=None)
    op.drop_column('gate_matrix', 'legal_basis_article')
    op.drop_column('gate_matrix', 'legal_basis_doc')
    op.drop_column('gate_matrix', 'avoidance_certification')
    op.drop_column('gate_matrix', 'avoidance_redesign')
    op.drop_column('gate_matrix', 'acquire_method')
