"""Link a verified local MinIO receipt to the immutable document v1 row."""

import argparse
import json
import os
from pathlib import Path
from uuid import UUID

import psycopg

from apps.api.app.services.contract_evidence import EXPECTED_SHA256
from datasets.generator.check_minio_contract import BUCKET, object_key
from datasets.generator.seed_price_case import database_id


def validate_receipt(receipt: dict) -> tuple[str, str, str, str]:
    expected = {"bucket", "object_key", "object_version_id", "sha256", "document_version"}
    if not isinstance(receipt, dict) or set(receipt) != expected:
        raise ValueError("Unexpected MinIO receipt fields")
    if (receipt["bucket"] != BUCKET
            or receipt["object_key"] != object_key(EXPECTED_SHA256)
            or receipt["sha256"] != EXPECTED_SHA256
            or receipt["document_version"] != 1):
        raise ValueError("Receipt disagrees with contract document v1")
    try:
        version = str(UUID(receipt["object_version_id"]))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("Receipt has no valid MinIO version ID") from exc
    if version != receipt["object_version_id"]:
        raise ValueError("MinIO version ID must be canonical")
    return receipt["bucket"], receipt["object_key"], version, receipt["sha256"]


def register(receipt_path: Path) -> None:
    bucket, key, version_id, sha256 = validate_receipt(
        json.loads(receipt_path.read_text(encoding="utf-8"))
    )

    def identifier(label):
        return database_id("DEMO-001", label)

    document_id = identifier("CON-001/document/v1")
    with psycopg.connect(
        host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
        dbname="procuregraph", user="postgres", password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT d.tenant_id, d.contract_id, d.version, d.sha256, d.mime,
                       d.storage_backend, d.object_key, e.page, e.price_clause,
                       e.tolerance_clause, e.dates_clause
                FROM documents d JOIN contract_line_evidence e ON e.document_id = d.id
                WHERE d.id = %s AND e.contract_line_id = %s FOR UPDATE OF d
            """, (document_id, identifier("CL-001")))
            stored = cursor.fetchone()
            expected = (identifier("TENANT"), identifier("CON-001"), 1, sha256,
                        "application/pdf", "fixture", None, 1, "2.1", "2.2", "2.3")
            if stored != expected:
                raise ValueError("Stored document or price-term link disagrees with the receipt")
            cursor.execute("""
                SELECT bucket, object_key, object_version_id, sha256
                FROM document_object_locations WHERE document_id = %s
            """, (document_id,))
            existing = cursor.fetchone()
            location = (bucket, key, version_id, sha256)
            if existing is not None:
                if existing != location:
                    raise ValueError("A different immutable object location is already registered")
                print("PASS: existing MinIO location matches; no rows changed")
                return
            cursor.execute("""
                INSERT INTO document_object_locations
                    (document_id, bucket, object_key, object_version_id, sha256)
                VALUES (%s, %s, %s, %s, %s)
            """, (document_id, *location))
    print("PASS: MinIO object location linked to document v1 without changing its record")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    register(args.receipt)


if __name__ == "__main__":
    main()
