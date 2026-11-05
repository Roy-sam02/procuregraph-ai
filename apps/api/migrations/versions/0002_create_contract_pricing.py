"""Create the contract side of the synthetic price case."""

import sqlalchemy as sa
from alembic import op

revision = "0002_create_contract_pricing"
down_revision = "0001_create_organizations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("legal_name", sa.Text(), nullable=False),
        sa.Column("tax_id_hash", sa.Text()),
        sa.Column("bank_account_hash", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
    )
    op.create_table(
        "contracts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("supplier_id", sa.Uuid(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("object_key", sa.Text()),
        sa.CheckConstraint("end_date >= start_date", name="ck_contract_dates"),
    )
    op.create_table(
        "contract_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "contract_id",
            sa.Uuid(),
            sa.ForeignKey("contracts.id", name="fk_contract_lines_contract"),
            nullable=False,
        ),
        sa.Column("product_id", sa.Uuid(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=False),
        sa.Column("max_unit_price", sa.Numeric(), nullable=False),
        sa.Column("tolerance_pct", sa.Numeric(), nullable=False),
        sa.CheckConstraint("effective_to >= effective_from", name="ck_contract_line_dates"),
        sa.CheckConstraint("max_unit_price >= 0", name="ck_contract_line_price"),
        sa.CheckConstraint("tolerance_pct >= 0", name="ck_contract_line_tolerance"),
    )


def downgrade() -> None:
    op.drop_table("contract_lines")
    op.drop_table("contracts")
    op.drop_table("products")
    op.drop_table("suppliers")
