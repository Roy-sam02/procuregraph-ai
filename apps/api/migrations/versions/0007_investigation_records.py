"""Store tenant-scoped investigation outcomes and verified findings."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007_investigation_records"
down_revision = "0006_document_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investigations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_line_id", sa.Uuid(), sa.ForeignKey("invoice_lines.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_investigations_tenant_key"),
        sa.CheckConstraint("status IN ('complete', 'needs_review', 'abstained')",
                           name="ck_investigations_status"),
    )
    op.create_index("ix_investigations_tenant_id", "investigations", ["tenant_id", "id"])
    op.create_table(
        "findings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("investigation_id", sa.Uuid(), sa.ForeignKey("investigations.id"),
                  nullable=False, unique=True),
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("is_violation", sa.Boolean(), nullable=False),
        sa.Column("evidence_json", JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("findings")
    op.drop_index("ix_investigations_tenant_id", table_name="investigations")
    op.drop_table("investigations")
