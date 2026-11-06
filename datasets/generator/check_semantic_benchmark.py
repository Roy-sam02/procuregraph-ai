"""Local semantic Qdrant benchmark against the same PostgreSQL lexical fixture."""

import argparse
import json
import math
import time
from importlib.metadata import version
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from apps.api.app.services.qdrant_hash_demo import request_json
from apps.api.app.services.retrieval_benchmark import (
    fixture_sha256, latency_summary, load_fixture, score_queries,
)
from apps.api.app.services.semantic_embeddings import DIMENSIONS, MODEL_NAME, LocalEncoder

COLLECTION = "procuregraph_bge_small_benchmark_v1"


def point_id(dataset_id: str, passage_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"procuregraph/benchmark/{dataset_id}/{passage_id}"))


def unit_vector(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if not magnitude or not math.isfinite(magnitude):
        raise ValueError("Invalid semantic vector magnitude")
    return [value / magnitude for value in vector]


def check(fixture_path: Path, lexical_path: Path, report_path: Path,
          endpoint: str, cache_dir: Path, encoder=None) -> dict:
    fixture = load_fixture(fixture_path)
    lexical = json.loads(lexical_path.read_text(encoding="utf-8"))
    if (lexical.get("fixture_sha256") != fixture_sha256(fixture_path)
            or lexical.get("dataset_id") != fixture["dataset_id"]
            or lexical.get("tenant_id") != fixture["tenant_id"]
            or len(lexical.get("queries", [])) != len(fixture["queries"])
            or any((row["text"], row["gold"], row["kind"]) !=
                   (item["text"], item["gold"], item["kind"])
                   for row, item in zip(lexical["queries"], fixture["queries"]))):
        raise ValueError("PostgreSQL results do not match the locked fixture")
    encoder = encoder or LocalEncoder(cache_dir)
    started = time.perf_counter()
    doc_vectors = encoder.encode([p["text"] for p in fixture["passages"]])
    query_vectors = encoder.encode([q["text"] for q in fixture["queries"]])
    embedding_ms = (time.perf_counter() - started) * 1000
    if len(doc_vectors) != 16 or len(query_vectors) != 32:
        raise ValueError("Missing model vectors")

    points = [{"id": point_id(fixture["dataset_id"], passage["id"]), "vector": vector,
               "payload": {"dataset_id": fixture["dataset_id"],
                           "tenant_id": fixture["tenant_id"],
                           "passage_id": passage["id"], "model": MODEL_NAME}}
              for passage, vector in zip(fixture["passages"], doc_vectors)]
    path = f"/collections/{COLLECTION}"
    collection = request_json(endpoint, "GET", path)
    if collection is None:
        request_json(endpoint, "PUT", path, {"vectors": {"size": DIMENSIONS, "distance": "Cosine"}})
    else:
        vectors = collection["result"]["config"]["params"]["vectors"]
        if vectors.get("size") != DIMENSIONS or vectors.get("distance") != "Cosine":
            raise ValueError("Existing semantic collection has a different vector schema")
    count = request_json(endpoint, "POST", f"{path}/points/count", {"exact": True})["result"]["count"]
    if count not in (0, len(points)):
        raise ValueError("Unexpected semantic collection point count")
    existing = request_json(endpoint, "POST", f"{path}/points", {
        "ids": [p["id"] for p in points], "with_payload": True, "with_vector": True,
    })["result"]
    if existing:
        if count != len(points) or len(existing) != len(points):
            raise ValueError("Partial semantic collection; no points overwritten")
        expected = {p["id"]: p for p in points}
        for stored in existing:
            wanted = expected.get(stored["id"])
            if (wanted is None or stored["payload"] != wanted["payload"]
                    or len(stored["vector"]) != DIMENSIONS
                    or any(not math.isclose(a, b, abs_tol=1e-4)
                           for a, b in zip(unit_vector(stored["vector"]),
                                           unit_vector(wanted["vector"])))):
                raise ValueError("Existing semantic point differs; no points overwritten")
    else:
        if count:
            raise ValueError("Semantic collection has unknown points")
        result = request_json(endpoint, "PUT", f"{path}/points?wait=true", {"points": points})
        if result["result"].get("status") != "completed":
            raise ValueError("Semantic upsert did not complete")
    final_count = request_json(endpoint, "POST", f"{path}/points/count", {"exact": True})["result"]["count"]
    if final_count != len(points):
        raise ValueError("Semantic collection does not contain all passages")

    expected_by_id = {p["id"]: p for p in points}
    evaluations = []
    for item, query_vector in zip(lexical["queries"], query_vectors):
        body = {"query": query_vector, "filter": {"must": [
            {"key": "dataset_id", "match": {"value": fixture["dataset_id"]}},
            {"key": "tenant_id", "match": {"value": fixture["tenant_id"]}},
        ]}, "limit": 10, "with_payload": True}
        started = time.perf_counter()
        hits = request_json(endpoint, "POST", f"{path}/points/query", body)["result"]["points"]
        query_ms = (time.perf_counter() - started) * 1000
        dense_ids = []
        for hit in hits:
            wanted = expected_by_id.get(hit["id"])
            if wanted is None or hit["payload"] != wanted["payload"]:
                raise ValueError("Semantic result lacks the expected source payload")
            dense_ids.append(wanted["payload"]["passage_id"])
        evaluations.append({**item, "dense_ids": dense_ids, "dense_query_ms": query_ms})
    other = request_json(endpoint, "POST", f"{path}/points/query", {
        "query": query_vectors[0], "filter": {"must": [
            {"key": "dataset_id", "match": {"value": fixture["dataset_id"]}},
            {"key": "tenant_id", "match": {"value": "OTHER-TENANT"}},
        ]}, "limit": 10,
    })["result"]["points"]
    if other:
        raise ValueError("Semantic search returned another tenant's points")

    report = {
        "scope": "locked_synthetic_diagnostic_not_real_world_quality",
        "dataset_id": fixture["dataset_id"], "fixture_sha256": lexical["fixture_sha256"],
        "passages": len(points), "queries": len(evaluations),
        "model": MODEL_NAME, "fastembed_version": version("fastembed") if encoder.__class__ is LocalEncoder else "mock",
        "embedding_ms_total": embedding_ms,
        "postgres_fts": {"metrics": score_queries(evaluations, "postgres_ids"),
                         "query_latency": latency_summary([q["postgres_query_ms"] for q in evaluations])},
        "qdrant_dense": {"metrics": score_queries(evaluations, "dense_ids"),
                         "query_latency_excluding_embedding": latency_summary([q["dense_query_ms"] for q in evaluations])},
        "failures_at_1": [{"query": q["text"], "gold": q["gold"], "kind": q["kind"],
                           "postgres_top1": q["postgres_ids"][0] if q["postgres_ids"] else None,
                           "dense_top1": q["dense_ids"][0] if q["dense_ids"] else None}
                          for q in evaluations if not q["postgres_ids"] or q["postgres_ids"][0] != q["gold"]
                          or not q["dense_ids"] or q["dense_ids"][0] != q["gold"]],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: evaluated {len(points)} synthetic passages and {len(evaluations)} labeled queries")
    print("PASS: tenant filter returned no points for another tenant; comparison report saved")
    print("PostgreSQL Recall@5: {:.3f}; semantic Qdrant Recall@5: {:.3f}".format(
        report["postgres_fts"]["metrics"]["all"]["recall_at_5"],
        report["qdrant_dense"]["metrics"]["all"]["recall_at_5"],
    ))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("lexical", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--cache-dir", type=Path, default=Path(".local-fixtures/fastembed_cache"))
    args = parser.parse_args()
    check(args.fixture, args.lexical, args.report, args.endpoint, args.cache_dir)


if __name__ == "__main__":
    main()
