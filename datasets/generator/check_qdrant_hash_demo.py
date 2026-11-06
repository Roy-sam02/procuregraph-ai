"""Index three source IDs and compare labeled smoke queries to PostgreSQL rankings."""

import argparse
import json
from pathlib import Path

from apps.api.app.services.qdrant_hash_demo import index_snapshot, search, validate_snapshot
from datasets.generator.seed_price_case import database_id


def check(snapshot_path: Path, endpoint: str, report_path: Path) -> dict:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    passages = validate_snapshot(snapshot)
    first = index_snapshot(snapshot, endpoint)
    assert not index_snapshot(snapshot, endpoint), "Repeat indexing changed Qdrant points"
    print("PASS: Qdrant has three source-linked points; repeat indexing changed no points")

    clauses = {p["id"]: p["clause"] for p in passages}
    results = []
    for item in snapshot["queries"]:
        query, expected = item["query"], item["expected_clause"]
        if not item["postgres_ids"] or clauses[item["postgres_ids"][0]] != expected:
            raise ValueError("PostgreSQL ranking lacks the labeled source")
        hits = search(snapshot, endpoint, query, snapshot["tenant_id"], top_k=3)
        if not hits or hits[0]["clause"] != expected:
            raise ValueError(f"Qdrant did not retrieve labeled clause {expected}")
        results.append({"query": query, "expected_clause": expected,
                        "postgres_top1_id": item["postgres_ids"][0],
                        "qdrant_top1_id": hits[0]["source_id"]})
    wrong_tenant = str(database_id("OTHER", "TENANT"))
    if search(snapshot, endpoint, "tolerance", wrong_tenant):
        raise ValueError("Qdrant tenant filter returned another tenant's source")
    report = {"scope": "three_synthetic_clause_smoke_not_retrieval_benchmark",
              "vectorizer": snapshot["vectorizer"], "queries": results,
              "top1_labeled_hits": len(results), "total_queries": len(results),
              "new_points_written": first}
    if report_path.exists():
        # The first-run flag is operational state, not part of the stable report.
        previous = json.loads(report_path.read_text(encoding="utf-8"))
        if {k: v for k, v in previous.items() if k != "new_points_written"} != {
            k: v for k, v in report.items() if k != "new_points_written"
        }:
            raise ValueError("Existing query comparison differs; no report overwritten")
        print("PASS: existing three-query comparison matches; no report changed")
    else:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("PASS: three labeled queries found the expected clauses in PostgreSQL and Qdrant; other tenant got no hits")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    check(args.snapshot, args.endpoint, args.report)


if __name__ == "__main__":
    main()
