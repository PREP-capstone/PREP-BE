"""add evidence_documents and evidence_chunks tables

Revision ID: d7a8c2f1b934
Revises: c6fd133b8e9e
Create Date: 2026-07-29 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d7a8c2f1b934"
down_revision: Union[str, Sequence[str], None] = "c6fd133b8e9e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "evidence_documents",
        sa.Column("document_id", sa.String(length=160), nullable=False),
        sa.Column("law_id", sa.String(length=120), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("doc_type", sa.String(length=20), nullable=False),
        sa.Column("source_subtype", sa.String(length=50), nullable=True),
        sa.Column("issuing_org", sa.String(length=200), nullable=True),
        sa.Column("jurisdiction", sa.String(length=10), nullable=False),
        sa.Column("rag_category", sa.String(length=200), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("tag_regulatory", sa.Boolean(), nullable=False),
        sa.Column("tag_privacy", sa.Boolean(), nullable=False),
        sa.Column("tag_advertising", sa.Boolean(), nullable=False),
        sa.Column("usage_scope", sa.String(length=20), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("collection_source", sa.String(length=100), nullable=True),
        sa.Column("processing_note", sa.Text(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("document_id"),
    )
    op.create_index("ix_evidence_documents_doc_type", "evidence_documents", ["doc_type"])
    op.create_index("ix_evidence_documents_status", "evidence_documents", ["status"])
    op.create_index("ix_evidence_documents_usage_scope", "evidence_documents", ["usage_scope"])
    op.create_index(
        "ix_evidence_documents_tags",
        "evidence_documents",
        ["tag_regulatory", "tag_privacy", "tag_advertising"],
    )

    op.create_table(
        "evidence_chunks",
        sa.Column("chunk_id", sa.String(length=220), nullable=False),
        sa.Column("document_id", sa.String(length=160), nullable=False),
        sa.Column("chunk_order", sa.Integer(), nullable=False),
        sa.Column("section_id", sa.String(length=100), nullable=True),
        sa.Column("section_title", sa.String(length=300), nullable=True),
        sa.Column("chunk_type", sa.String(length=40), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=True),
        sa.Column("tag_regulatory", sa.Boolean(), nullable=False),
        sa.Column("tag_privacy", sa.Boolean(), nullable=False),
        sa.Column("tag_advertising", sa.Boolean(), nullable=False),
        sa.Column("case_tag_advertising", sa.Boolean(), nullable=False),
        sa.Column("case_tag_privacy", sa.Boolean(), nullable=False),
        sa.Column("case_tag_medical_device", sa.Boolean(), nullable=False),
        sa.Column("case_tag_health_functional_food", sa.Boolean(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("local_file_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["evidence_documents.document_id"]),
        sa.PrimaryKeyConstraint("chunk_id"),
    )
    op.create_index("ix_evidence_chunks_document_id", "evidence_chunks", ["document_id"])
    op.create_index("ix_evidence_chunks_section_id", "evidence_chunks", ["section_id"])
    op.create_index("ix_evidence_chunks_chunk_type", "evidence_chunks", ["chunk_type"])
    op.create_index("ix_evidence_chunks_status", "evidence_chunks", ["status"])
    op.create_index(
        "ix_evidence_chunks_tags",
        "evidence_chunks",
        ["tag_regulatory", "tag_privacy", "tag_advertising"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_evidence_chunks_tags", table_name="evidence_chunks")
    op.drop_index("ix_evidence_chunks_status", table_name="evidence_chunks")
    op.drop_index("ix_evidence_chunks_chunk_type", table_name="evidence_chunks")
    op.drop_index("ix_evidence_chunks_section_id", table_name="evidence_chunks")
    op.drop_index("ix_evidence_chunks_document_id", table_name="evidence_chunks")
    op.drop_table("evidence_chunks")

    op.drop_index("ix_evidence_documents_tags", table_name="evidence_documents")
    op.drop_index("ix_evidence_documents_usage_scope", table_name="evidence_documents")
    op.drop_index("ix_evidence_documents_status", table_name="evidence_documents")
    op.drop_index("ix_evidence_documents_doc_type", table_name="evidence_documents")
    op.drop_table("evidence_documents")
