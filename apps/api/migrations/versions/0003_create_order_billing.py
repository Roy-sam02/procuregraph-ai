"""Create purchase orders and invoices for the synthetic price case."""

import sqlalchemy as sa
from alembic import op

revision = "0003_create_order_billing"
down_revision = "0002_create_contract_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("supplier_id", sa.Uuid(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("contract_id", sa.Uuid(), sa.ForeignKey("contracts.id"), nullable=False),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
    )
    op.create_table(
        "po_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("po_id", sa.Uuid(), sa.ForeignKey("purchase_orders.id"), nullable=False),
        sa.Column("product_id", sa.Uuid(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("unit_price", sa.Numeric(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_po_lines_quantity"),
        sa.CheckConstraint("unit_price >= 0", name="ck_po_lines_unit_price"),
    )
    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("supplier_id", sa.Uuid(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("po_id", sa.Uuid(), sa.ForeignKey("purchase_orders.id"), nullable=False),
        sa.Column("invoice_number", sa.Text(), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
    )
    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("invoice_id", sa.Uuid(), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column(
            "po_line_id",
            sa.Uuid(),
            sa.ForeignKey("po_lines.id", name="fk_invoice_lines_po_line"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(), nullable=False),
        sa.Column("unit_price", sa.Numeric(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_invoice_lines_quantity"),
        sa.CheckConstraint("unit_price >= 0", name="ck_invoice_lines_unit_price"),
    )


def downgrade() -> None:
    op.drop_table("invoice_lines")
    op.drop_table("invoices")
    op.drop_table("po_lines")
    op.drop_table("purchase_orders")
