"""Export checked PostgreSQL chunks and three labeled lexical queries."""

import argparse
import json
import os
from pathlib import Path

import psycopg

from apps.api.app.services.hash_vectors import MODEL_ID
from apps.api.app.services.passage_search import search_passages
from datasets.generator.export_evidence_locator import read_locator
from datasets.generator.register_contract_passages import SELECT_CHUNKS, passage_row
from datasets.generator.seed_price_case import database_id

QUERIES = (
    ("maximum unit price for product", "2.1"),
    ("price tolerance above allowed", "2.2"),
    ("effective period apply", "2.3"),
)


def export(manifest_path: Path, output: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tenant = database_id("DEMO-001", "TENANT")
    with psycopg.connect(
        host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
        dbname="procuregraph", user="postgres", password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
    ) as connection:
        locator = read_locator(connection, tenant, database_id("DEMO-001", "CL-001"))
        if (manifest.get("document_id") != locator["document_id"]
                or manifest.get("document_version") != locator["document_version"]
                or manifest.get("source_sha256") != locator["sha256"]
                or len(manifest.get("passages", [])) != 3):
            raise ValueError("Manifest source does not match the stored contract")
        expected = tuple(passage_row(p) for p in manifest["passages"])
        with connection.cursor() as cursor:
            cursor.execute(SELECT_CHUNKS, (database_id("DEMO-001", "CON-001/document/v1"),))
            if tuple(cursor.fetchall()) != expected:
                raise ValueError("PostgreSQL chunks differ from the verified manifest")
        rankings = []
        for query, clause in QUERIES:
            results = search_passages(connection, tenant, query, top_k=3)
            if not results or results[0]["clause"] != clause:
                raise ValueError(f"Lexical baseline did not find clause {clause}: {query}")
            rankings.append({"query": query, "expected_clause": clause,
                             "postgres_ids": [item["source_id"] for item in results]})
    snapshot = {"schema_version": 1, "vectorizer": MODEL_ID,
                "tenant_id": str(tenant), "document_id": locator["document_id"],
                "document_version": locator["document_version"],
                "source_sha256": locator["sha256"],
                "passages": manifest["passages"], "queries": rankings}
    if output.exists():
        if json.loads(output.read_text(encoding="utf-8")) != snapshot:
            raise ValueError("Existing vector snapshot differs; it was not overwritten")
        print("PASS: existing PostgreSQL vector snapshot matches; no file changed")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("PASS: exported three verified PostgreSQL chunks and labeled lexical rankings")
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    export(args.manifest, args.output)


if __name__ == "__main__":
    main()
