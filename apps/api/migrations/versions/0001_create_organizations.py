"""Create the synthetic demo organizations table."""

import sqlalchemy as sa
from alembic import op

revision = "0001_create_organizations"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("organizations")
