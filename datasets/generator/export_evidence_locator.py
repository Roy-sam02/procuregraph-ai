"""Export one tenant-scoped, stored source locator while PostgreSQL runs."""

import argparse
import json
import os
from decimal import Decimal
from pathlib import Path

import psycopg

from apps.api.app.services.contract_evidence import EXPECTED_SHA256
from datasets.generator.register_minio_location import validate_receipt
from datasets.generator.seed_price_case import database_id


def export_locator(output: Path) -> dict:
    def identifier(label):
        return database_id("DEMO-001", label)

    with psycopg.connect(
        host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
        dbname="procuregraph", user="postgres", password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT d.id, d.tenant_id, d.contract_id, d.version, d.sha256,
                       d.mime, d.page_count, d.storage_backend, d.object_key,
                       l.bucket, l.object_key, l.object_version_id, l.sha256,
                       e.page, e.price_clause, e.tolerance_clause, e.dates_clause,
                       cl.id, cl.max_unit_price, cl.tolerance_pct,
                       cl.effective_from, cl.effective_to, c.currency, s.tenant_id
                FROM contract_line_evidence e
                JOIN contract_lines cl ON cl.id = e.contract_line_id
                JOIN contracts c ON c.id = cl.contract_id
                JOIN suppliers s ON s.id = c.supplier_id
                JOIN documents d ON d.id = e.document_id
                    AND d.contract_id = c.id AND d.tenant_id = s.tenant_id
                JOIN document_object_locations l ON l.document_id = d.id
                WHERE cl.id = %s AND s.tenant_id = %s
            """, (identifier("CL-001"), identifier("TENANT")))
            rows = cursor.fetchall()
    if len(rows) != 1:
        raise ValueError("Expected one linked document for this tenant and price term")
    (doc_id, tenant_id, contract_id, version, sha, mime, pages, backend, doc_key,
     bucket, key, object_version, object_sha, page, price_clause, tolerance_clause,
     dates_clause, line_id, price, tolerance, effective_from, effective_to,
     currency, supplier_tenant) = rows[0]
    if (doc_id, tenant_id, contract_id, version, sha, mime, pages, backend, doc_key,
        line_id, price, tolerance, effective_from.isoformat(), effective_to.isoformat(),
        currency, supplier_tenant, page, price_clause, tolerance_clause, dates_clause) != (
            identifier("CON-001/document/v1"), identifier("TENANT"), identifier("CON-001"),
            1, EXPECTED_SHA256, "application/pdf", 1, "fixture", None,
            identifier("CL-001"), Decimal("100.00"), Decimal("5.00"),
            "2025-01-01", "2025-12-31", "INR", identifier("TENANT"),
            1, "2.1", "2.2", "2.3"):
        raise ValueError("Stored source or price term is inconsistent")
    validate_receipt({"bucket": bucket, "object_key": key,
                      "object_version_id": object_version, "sha256": object_sha,
                      "document_version": version})
    locator = {
        "tenant_id": str(tenant_id), "contract_id": str(contract_id),
        "contract_line_id": str(line_id), "document_id": str(doc_id),
        "document_version": version, "sha256": sha,
        "bucket": bucket, "object_key": key, "object_version_id": object_version,
        "page": page, "price_clause": price_clause,
        "tolerance_clause": tolerance_clause, "dates_clause": dates_clause,
        "max_unit_price": str(price), "tolerance_pct": str(tolerance), "currency": currency,
    }
    if output.exists():
        if json.loads(output.read_text(encoding="utf-8")) != locator:
            raise ValueError("Existing locator differs; it was not overwritten")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(locator, indent=2) + "\n", encoding="utf-8")
    print("PASS: exported stored document v1 locator with tenant, price term, and MinIO version")
    return locator


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    export_locator(args.output)


if __name__ == "__main__":
    main()
