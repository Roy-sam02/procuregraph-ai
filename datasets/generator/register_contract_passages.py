"""Register only passages regenerated from the database-linked MinIO version."""

import argparse
import json
import os
from pathlib import Path
from uuid import UUID

import psycopg

from apps.api.app.ingestion.contract_passages import extract_contract_passages
from datasets.generator.export_evidence_locator import read_locator
from datasets.generator.seed_price_case import database_id
from datasets.generator.verify_evidence_locator import read_verified_pdf


SELECT_CHUNKS = """
SELECT id, tenant_id, contract_id, document_id, document_version,
       source_sha256, page, clause, start_offset, end_offset,
       page_text_hash, text_hash, passage_text
FROM document_chunks WHERE document_id = %s ORDER BY clause
"""

INSERT_CHUNK = """
INSERT INTO document_chunks (
    id, tenant_id, contract_id, document_id, document_version,
    source_sha256, page, clause, start_offset, end_offset,
    page_text_hash, text_hash, passage_text
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def passage_row(passage: dict) -> tuple:
    return (
        UUID(passage["id"]), UUID(passage["tenant_id"]), UUID(passage["contract_id"]),
        UUID(passage["document_id"]), passage["document_version"],
        passage["source_sha256"], passage["page"], passage["clause"],
        passage["start_offset"], passage["end_offset"],
        passage["page_text_hash"], passage["text_hash"], passage["text"],
    )


def register(manifest_path: Path, endpoint: str) -> int:
    supplied = json.loads(manifest_path.read_text(encoding="utf-8"))
    with psycopg.connect(
        host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
        dbname="procuregraph", user="postgres", password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
    ) as connection:
        locator = read_locator(
            connection, database_id("DEMO-001", "TENANT"), database_id("DEMO-001", "CL-001")
        )
        pdf, _ = read_verified_pdf(locator, endpoint)
        expected = extract_contract_passages(pdf, locator)
        if supplied != expected:
            raise ValueError("Passage manifest differs from the verified stored PDF")

        rows = tuple(passage_row(p) for p in expected["passages"])
        document_id = UUID(locator["document_id"])
        with connection.cursor() as cursor:
            cursor.execute(SELECT_CHUNKS, (document_id,))
            existing = tuple(cursor.fetchall())
            if existing:
                if existing != rows:
                    raise ValueError("Existing immutable chunks differ; no rows changed")
                print("PASS: three PostgreSQL passages already match; no rows changed")
                return 0
            for row in rows:
                cursor.execute(INSERT_CHUNK, row)
    print("PASS: registered three verified, immutable clause passages in PostgreSQL")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    register(args.manifest, args.endpoint)


if __name__ == "__main__":
    main()
