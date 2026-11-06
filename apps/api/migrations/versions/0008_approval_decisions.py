"""Store one immutable reviewer decision per verified price finding."""

import sqlalchemy as sa
from alembic import op

revision = "0008_approval_decisions"
down_revision = "0007_investigation_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), sa.ForeignKey("findings.id"), nullable=False,
                  unique=True),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_approvals_tenant_key"),
        sa.CheckConstraint("decision IN ('approved', 'rejected')", name="ck_approvals_decision"),
        sa.CheckConstraint("char_length(btrim(reason)) BETWEEN 1 AND 1000",
                           name="ck_approvals_reason"),
    )
    op.execute("""
        CREATE FUNCTION forbid_approval_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Approval decisions are immutable';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER approvals_immutable BEFORE UPDATE OR DELETE ON approvals
        FOR EACH ROW EXECUTE FUNCTION forbid_approval_change()
    """)


def downgrade() -> None:
    op.drop_table("approvals")
    op.execute("DROP FUNCTION forbid_approval_change()")
