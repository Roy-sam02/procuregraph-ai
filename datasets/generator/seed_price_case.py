"""Seed and verify one synthetic contract price case."""

import argparse
import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import psycopg

from apps.api.app.domain.pricing import assess_price_case


def database_id(tenant_label: str, record_label: str):
    return uuid5(NAMESPACE_URL, f"procuregraph-ai/{tenant_label}/{record_label}")


def load_case(path: Path) -> dict:
    case = json.loads(path.read_text(encoding="utf-8"))
    assess_price_case(case)
    return case


def seed_and_verify(case: dict) -> None:
    tenant_label = case["tenant_id"]
    supplier = case["supplier"]
    terms = case["contract_line"]
    order = case["purchase_order"]
    ordered_line = case["po_line"]
    invoice = case["invoice"]
    billed_line = case["invoice_line"]

    def identifier(label: str):
        return database_id(tenant_label, label)

    tenant_id = identifier("TENANT")
    organization_id = identifier("ORGANIZATION")
    contract_id = identifier(terms["contract_id"])
    product_id = identifier(terms["product_id"])

    with psycopg.connect(
        host="127.0.0.1",
        port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
        dbname="procuregraph",
        user="postgres",
        password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM suppliers WHERE id = %s",
                (identifier(supplier["id"]),),
            )
            if cursor.fetchone() is not None:
                raise ValueError("This synthetic supplier is already seeded")

            cursor.execute(
                "INSERT INTO organizations (id, name, tenant_id) VALUES (%s, %s, %s)",
                (organization_id, "Synthetic Procurement Lab", tenant_id),
            )
            cursor.execute(
                """INSERT INTO suppliers (id, tenant_id, legal_name, status)
                   VALUES (%s, %s, %s, %s)""",
                (identifier(supplier["id"]), tenant_id, supplier["name"], "active"),
            )
            cursor.execute(
                """INSERT INTO products (id, sku, category, unit)
                   VALUES (%s, %s, %s, %s)""",
                (product_id, terms["product_id"], "office supplies", "each"),
            )
            cursor.execute(
                """INSERT INTO contracts
                   (id, supplier_id, start_date, end_date, currency)
                   VALUES (%s, %s, %s, %s, %s)""",
                (
                    contract_id, identifier(supplier["id"]),
                    date(2025, 1, 1), date(2025, 12, 31), terms["currency"],
                ),
            )
            cursor.execute(
                """INSERT INTO contract_lines
                   (id, contract_id, product_id, effective_from, effective_to,
                    max_unit_price, tolerance_pct)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    identifier(terms["id"]), contract_id, product_id,
                    date(2025, 1, 1), date(2025, 12, 31),
                    Decimal(terms["max_unit_price"]), Decimal(terms["tolerance_pct"]),
                ),
            )
            cursor.execute(
                """INSERT INTO purchase_orders
                   (id, supplier_id, contract_id, ordered_at, status)
                   VALUES (%s, %s, %s, %s, %s)""",
                (
                    identifier(order["id"]), identifier(supplier["id"]), contract_id,
                    datetime(2025, 3, 1, 9, tzinfo=timezone.utc), "issued",
                ),
            )
            cursor.execute(
                """INSERT INTO po_lines (id, po_id, product_id, quantity, unit_price)
                   VALUES (%s, %s, %s, %s, %s)""",
                (
                    identifier(ordered_line["id"]), identifier(order["id"]), product_id,
                    Decimal(ordered_line["quantity"]), Decimal(ordered_line["unit_price"]),
                ),
            )
            cursor.execute(
                """INSERT INTO invoices
                   (id, supplier_id, po_id, invoice_number, invoice_date, currency)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    identifier(invoice["id"]), identifier(supplier["id"]),
                    identifier(order["id"]), invoice["id"], date(2025, 3, 15),
                    invoice["currency"],
                ),
            )
            cursor.execute(
                """INSERT INTO invoice_lines
                   (id, invoice_id, po_line_id, quantity, unit_price)
                   VALUES (%s, %s, %s, %s, %s)""",
                (
                    identifier(billed_line["id"]), identifier(invoice["id"]),
                    identifier(ordered_line["id"]),
                    Decimal(billed_line["quantity"]), Decimal(billed_line["unit_price"]),
                ),
            )

            cursor.execute(
                """SELECT s.legal_name, p.sku, c.currency, cl.max_unit_price,
                          cl.tolerance_pct, il.quantity, il.unit_price,
                          po.id = i.po_id, pol.product_id = cl.product_id,
                          s.id = po.supplier_id AND s.id = i.supplier_id,
                          c.currency = i.currency,
                          c.start_date <= i.invoice_date
                            AND i.invoice_date <= c.end_date,
                          cl.effective_from <= i.invoice_date
                            AND i.invoice_date <= cl.effective_to
                   FROM invoice_lines AS il
                   JOIN invoices AS i ON i.id = il.invoice_id
                   JOIN po_lines AS pol ON pol.id = il.po_line_id
                   JOIN purchase_orders AS po ON po.id = pol.po_id
                   JOIN contracts AS c ON c.id = po.contract_id
                   JOIN contract_lines AS cl
                     ON cl.contract_id = c.id AND cl.product_id = pol.product_id
                   JOIN products AS p ON p.id = pol.product_id
                   JOIN suppliers AS s ON s.id = c.supplier_id
                   WHERE il.id = %s AND cl.id = %s""",
                (identifier(billed_line["id"]), identifier(terms["id"])),
            )
            stored = cursor.fetchone()
            if stored is None:
                raise ValueError("The invoice line could not be traced to its price term")

            (
                stored_supplier, stored_sku, currency, max_price, tolerance,
                quantity, billed_price, same_order, same_product,
                same_supplier, same_currency, contract_active, price_active,
            ) = stored
            if (
                stored_supplier != supplier["name"]
                or stored_sku != terms["product_id"]
                or currency != invoice["currency"]
                or not all((
                    same_order, same_product, same_supplier, same_currency,
                    contract_active, price_active,
                ))
            ):
                raise ValueError("Stored links or dates do not match this synthetic case")

            stored_case = json.loads(json.dumps(case))
            stored_case["contract_line"]["max_unit_price"] = str(max_price)
            stored_case["contract_line"]["tolerance_pct"] = str(tolerance)
            stored_case["invoice_line"]["quantity"] = str(quantity)
            stored_case["invoice_line"]["unit_price"] = str(billed_price)
            result = assess_price_case(stored_case)
            if (
                result.allowed_unit_price != Decimal("105.00")
                or result.excess_amount != Decimal("10.00")
                or not result.is_violation
            ):
                raise ValueError("The database case gave an unexpected assessment")

            print(
                "PASS: stored synthetic case gives allowed INR "
                f"{result.allowed_unit_price} and excess INR {result.excess_amount}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    arguments = parser.parse_args()
    seed_and_verify(load_case(arguments.fixture))


if __name__ == "__main__":
    main()
