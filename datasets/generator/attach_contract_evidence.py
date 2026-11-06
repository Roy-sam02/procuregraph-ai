"""Attach a verified local PDF fixture to the existing synthetic price term."""

import argparse
import os
from decimal import Decimal
from pathlib import Path

import psycopg

from apps.api.app.services.contract_evidence import verify_synthetic_pdf
from datasets.generator.seed_price_case import database_id


def attach(pdf: Path, *, check_only: bool = False) -> None:
    verified = verify_synthetic_pdf(pdf)
    print(f"PASS: PDF page {verified.page}, clauses 2.1/2.2/2.3, SHA-256 {verified.sha256}")
    if check_only:
        return

    def identifier(label):
        return database_id("DEMO-001", label)

    tenant_id = identifier("TENANT")
    contract_id = identifier("CON-001")
    line_id = identifier("CL-001")
    document_id = identifier("CON-001/document/v1")
    with psycopg.connect(
        host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
        dbname="procuregraph", user="postgres",
        password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT s.tenant_id, p.sku, c.currency, c.start_date, c.end_date,
                       cl.effective_from, cl.effective_to, cl.max_unit_price, cl.tolerance_pct
                FROM contract_lines cl JOIN contracts c ON c.id = cl.contract_id
                JOIN suppliers s ON s.id = c.supplier_id JOIN products p ON p.id = cl.product_id
                WHERE cl.id = %s AND c.id = %s FOR UPDATE OF cl
            """, (line_id, contract_id))
            row = cursor.fetchone()
            if row is None or row[:3] != (tenant_id, "PROD-001", "INR"):
                raise ValueError("The expected tenant, contract, product, or currency is absent")
            if any(d.isoformat() != expected for d, expected in zip(
                row[3:7], ("2025-01-01", "2025-12-31", "2025-01-01", "2025-12-31")
            )) or row[7:] != (Decimal("100.00"), Decimal("5.00")):
                raise ValueError("Stored price term disagrees with the PDF")
            cursor.execute(
                "SELECT d.id, d.tenant_id, d.contract_id, d.sha256, d.version, d.storage_backend, e.page, "
                "e.price_clause, e.tolerance_clause, e.dates_clause "
                "FROM contract_line_evidence e JOIN documents d ON d.id = e.document_id "
                "WHERE e.contract_line_id = %s", (line_id,),
            )
            existing = cursor.fetchone()
            expected = (document_id, tenant_id, contract_id,
                        verified.sha256, verified.version, "fixture", verified.page,
                        verified.price_clause, verified.tolerance_clause, verified.dates_clause)
            if existing is not None:
                if existing != expected:
                    raise ValueError("Existing provenance differs; append a new version instead")
                print("PASS: existing fixture provenance matches; no rows changed")
                return
            cursor.execute("""
                INSERT INTO documents
                    (id, tenant_id, contract_id, version, sha256, mime,
                     storage_backend, object_key, page_count)
                VALUES (%s, %s, %s, %s, %s, 'application/pdf', 'fixture', NULL, 1)
            """, (document_id, tenant_id, contract_id, verified.version, verified.sha256))
            cursor.execute("""
                INSERT INTO contract_line_evidence
                    (contract_line_id, document_id, page, price_clause, tolerance_clause, dates_clause)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (line_id, document_id, verified.page, verified.price_clause,
                  verified.tolerance_clause, verified.dates_clause))
    print("PASS: immutable fixture metadata and price-term link stored in PostgreSQL")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    attach(args.pdf, check_only=args.check_only)


if __name__ == "__main__":
    main()
