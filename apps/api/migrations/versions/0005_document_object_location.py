"""Append-only location for a document's verified MinIO object version."""

import sqlalchemy as sa
from alembic import op

revision = "0005_document_object_location"
down_revision = "0004_contract_document_fixture"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_object_locations",
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id"), primary_key=True),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("object_version_id", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("bucket", "object_key", "object_version_id", name="uq_document_object_version"),
        sa.CheckConstraint("length(bucket) > 0", name="ck_object_bucket"),
        sa.CheckConstraint("length(object_key) > 0", name="ck_object_key"),
        sa.CheckConstraint("length(object_version_id) > 0", name="ck_object_version"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_object_sha256"),
    )
    op.execute("""
        CREATE TRIGGER document_object_locations_append_only
        BEFORE UPDATE OR DELETE ON document_object_locations
        FOR EACH ROW EXECUTE FUNCTION prevent_provenance_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER document_object_locations_append_only ON document_object_locations")
    op.drop_table("document_object_locations")
