"""Run the locked synthetic fixture through PostgreSQL full-text search."""

import argparse
import json
import os
from pathlib import Path

import psycopg

from apps.api.app.services.retrieval_benchmark import (
    fixture_sha256, load_fixture, postgres_ranking,
)


def export(fixture_path: Path, output: Path) -> dict:
    fixture = load_fixture(fixture_path)
    with psycopg.connect(
        host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
        dbname="procuregraph", user="postgres", password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
    ) as connection:
        queries = []
        for item in fixture["queries"]:
            ids, elapsed_ms = postgres_ranking(connection, fixture["passages"], item["text"])
            queries.append({**item, "postgres_ids": ids, "postgres_query_ms": elapsed_ms})
    snapshot = {"dataset_id": fixture["dataset_id"], "tenant_id": fixture["tenant_id"],
                "fixture_sha256": fixture_sha256(fixture_path), "queries": queries}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    print("PASS: PostgreSQL ranked 32 labeled synthetic procurement queries")
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    export(args.fixture, args.output)


if __name__ == "__main__":
    main()
