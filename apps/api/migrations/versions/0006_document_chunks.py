"""Append-only, versioned contract passages with PostgreSQL full-text indexing."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

revision = "0006_document_chunks"
down_revision = "0005_document_object_location"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This composite key lets PostgreSQL enforce the source identity on every chunk.
    op.create_unique_constraint(
        "uq_documents_chunk_identity", "documents",
        ["id", "tenant_id", "contract_id", "version", "sha256"],
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("contract_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("clause", sa.String(32), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("page_text_hash", sa.String(64), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("passage_text", sa.Text(), nullable=False),
        sa.Column(
            "search_vector", TSVECTOR(),
            sa.Computed("to_tsvector('english'::regconfig, passage_text)", persisted=True),
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "tenant_id", "contract_id", "document_version", "source_sha256"],
            ["documents.id", "documents.tenant_id", "documents.contract_id",
             "documents.version", "documents.sha256"],
            name="fk_chunk_source_identity",
        ),
        sa.UniqueConstraint("document_id", "page", "clause", name="uq_chunk_document_clause"),
        sa.CheckConstraint("document_version > 0 AND page > 0", name="ck_chunk_positive_version_page"),
        sa.CheckConstraint("start_offset >= 0 AND end_offset > start_offset", name="ck_chunk_offsets"),
        sa.CheckConstraint("length(passage_text) BETWEEN 1 AND 4000", name="ck_chunk_text_length"),
        sa.CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_chunk_source_hash"),
        sa.CheckConstraint("page_text_hash ~ '^[0-9a-f]{64}$'", name="ck_chunk_page_hash"),
        sa.CheckConstraint("text_hash ~ '^[0-9a-f]{64}$'", name="ck_chunk_text_hash"),
    )
    op.create_index("ix_document_chunks_fts", "document_chunks", ["search_vector"], postgresql_using="gin")
    op.create_index("ix_document_chunks_tenant", "document_chunks", ["tenant_id", "document_id"])
    op.execute("""
        CREATE TRIGGER document_chunks_append_only
        BEFORE UPDATE OR DELETE ON document_chunks
        FOR EACH ROW EXECUTE FUNCTION prevent_provenance_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER document_chunks_append_only ON document_chunks")
    op.drop_index("ix_document_chunks_tenant", table_name="document_chunks")
    op.drop_index("ix_document_chunks_fts", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_constraint("uq_documents_chunk_identity", "documents", type_="unique")
