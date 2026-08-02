"""add evidence_chunk_embeddings table

Revision ID: f29c0d21f2a8
Revises: d7a8c2f1b934
Create Date: 2026-08-02 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f29c0d21f2a8"
down_revision: Union[str, Sequence[str], None] = "d7a8c2f1b934"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "evidence_chunk_embeddings",
        sa.Column("chunk_id", sa.String(length=220), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "embedded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["chunk_id"], ["evidence_chunks.chunk_id"]),
        sa.PrimaryKeyConstraint("chunk_id"),
    )
    op.execute("ALTER TABLE evidence_chunk_embeddings ADD COLUMN embedding vector(1536) NOT NULL")
    op.create_index(
        "ix_evidence_chunk_embeddings_model",
        "evidence_chunk_embeddings",
        ["embedding_model"],
    )
    op.create_index(
        "ix_evidence_chunk_embeddings_content_hash",
        "evidence_chunk_embeddings",
        ["content_hash"],
    )
    op.execute(
        "CREATE INDEX ix_evidence_chunk_embeddings_vector_cosine "
        "ON evidence_chunk_embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_evidence_chunk_embeddings_vector_cosine")
    op.drop_index(
        "ix_evidence_chunk_embeddings_content_hash",
        table_name="evidence_chunk_embeddings",
    )
    op.drop_index("ix_evidence_chunk_embeddings_model", table_name="evidence_chunk_embeddings")
    op.drop_table("evidence_chunk_embeddings")
