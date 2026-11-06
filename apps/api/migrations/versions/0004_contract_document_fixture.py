"""Store immutable document metadata and one contract-price evidence link."""

import sqlalchemy as sa
from alembic import op

revision = "0004_contract_document_fixture"
down_revision = "0003_create_order_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("contract_id", sa.Uuid(), sa.ForeignKey("contracts.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("mime", sa.String(32), nullable=False),
        sa.Column("storage_backend", sa.String(16), nullable=False),
        sa.Column("object_key", sa.Text()),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("contract_id", "version", name="uq_document_contract_version"),
        sa.CheckConstraint("version > 0", name="ck_document_version"),
        sa.CheckConstraint("page_count > 0", name="ck_document_pages"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_document_sha256"),
        sa.CheckConstraint("mime = 'application/pdf'", name="ck_document_mime"),
        sa.CheckConstraint(
            "(storage_backend = 'fixture' AND object_key IS NULL) OR "
            "(storage_backend = 'minio' AND object_key IS NOT NULL)",
            name="ck_document_storage",
        ),
    )
    op.create_table(
        "contract_line_evidence",
        sa.Column("contract_line_id", sa.Uuid(), sa.ForeignKey("contract_lines.id"), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("price_clause", sa.Text(), nullable=False),
        sa.Column("tolerance_clause", sa.Text(), nullable=False),
        sa.Column("dates_clause", sa.Text(), nullable=False),
        sa.CheckConstraint("page > 0", name="ck_evidence_page"),
    )
    # A content hash has no meaning if its metadata can be rewritten in place.
    op.execute("""
        CREATE FUNCTION prevent_provenance_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Provenance rows are append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    for table in ("documents", "contract_line_evidence"):
        op.execute(f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION prevent_provenance_mutation()
        """)


def downgrade() -> None:
    for table in ("contract_line_evidence", "documents"):
        op.execute(f"DROP TRIGGER {table}_append_only ON {table}")
    op.drop_table("contract_line_evidence")
    op.drop_table("documents")
    op.execute("DROP FUNCTION prevent_provenance_mutation()")
