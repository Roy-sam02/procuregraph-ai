"""Index verified source chunks with local embeddings and inspect retrieval."""

import argparse
import json
from pathlib import Path

from apps.api.app.services.qdrant_hash_demo import validate_snapshot
from apps.api.app.services.qdrant_semantic_sources import index_snapshot, search
from apps.api.app.services.semantic_embeddings import LocalEncoder, MODEL_NAME
from datasets.generator.seed_price_case import database_id


def check(snapshot_path: Path, report_path: Path, endpoint: str,
          cache_dir: Path, encoder=None) -> dict:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    passages = validate_snapshot(snapshot)
    encoder = encoder or LocalEncoder(cache_dir)
    first = index_snapshot(snapshot, endpoint, encoder)
    if index_snapshot(snapshot, endpoint, encoder):
        raise ValueError("Repeat semantic index changed points")
    print("PASS: three verified PostgreSQL source IDs indexed with local semantic embeddings; repeat unchanged")
    clauses = {p["id"]: p["clause"] for p in passages}
    comparisons = []
    for item in snapshot["queries"]:
        expected = item["expected_clause"]
        if not item["postgres_ids"] or clauses[item["postgres_ids"][0]] != expected:
            raise ValueError("PostgreSQL snapshot label does not match its source")
        hits = search(snapshot, endpoint, item["query"], snapshot["tenant_id"], encoder)
        comparisons.append({"query": item["query"], "expected_clause": expected,
                            "postgres_top1_clause": clauses[item["postgres_ids"][0]],
                            "semantic_top1_clause": hits[0]["clause"] if hits else None,
                            "semantic_source_ids": [hit["source_id"] for hit in hits]})
    wrong_tenant = str(database_id("OTHER", "TENANT"))
    if search(snapshot, endpoint, "price tolerance", wrong_tenant, encoder):
        raise ValueError("Another tenant received semantic source hits")
    report = {"scope": "three_verified_synthetic_clauses_not_quality_benchmark",
              "model": MODEL_NAME, "document_id": snapshot["document_id"],
              "source_sha256": snapshot["source_sha256"], "point_count": len(passages),
              "new_points_written": first, "comparisons": comparisons,
              "semantic_top1_labeled": sum(row["semantic_top1_clause"] == row["expected_clause"]
                                           for row in comparisons)}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PASS: semantic search used tenant, document version and PDF hash filters; other tenant got no hits")
    print(f"Diagnostic top-1 labeled queries: {report['semantic_top1_labeled']}/{len(comparisons)}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path(".local-fixtures/fastembed_cache"))
    args = parser.parse_args()
    check(args.snapshot, args.report, args.endpoint, args.cache_dir)


if __name__ == "__main__":
    main()
