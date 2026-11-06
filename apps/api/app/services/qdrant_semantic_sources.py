"""Local semantic index of PostgreSQL-exported, verified contract chunks."""

import math

from apps.api.app.services.qdrant_hash_demo import request_json, validate_snapshot
from apps.api.app.services.semantic_embeddings import DIMENSIONS, MODEL_NAME

COLLECTION = "procuregraph_verified_bge_small_v1"


def unit_vector(values: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in values))
    if len(values) != DIMENSIONS or not math.isfinite(magnitude) or magnitude <= 0:
        raise ValueError("Invalid semantic vector")
    return [value / magnitude for value in values]


def source_payload(passage: dict) -> dict:
    return {
        "tenant_id": passage["tenant_id"], "document_id": passage["document_id"],
        "document_version": passage["document_version"],
        "source_sha256": passage["source_sha256"], "text_hash": passage["text_hash"],
        "page": passage["page"], "clause": passage["clause"],
        "start_offset": passage["start_offset"], "end_offset": passage["end_offset"],
        "model": MODEL_NAME,
    }


def point_for(passage: dict, vector: list[float]) -> dict:
    return {"id": passage["id"], "vector": unit_vector(vector),
            "payload": source_payload(passage)}


def index_snapshot(snapshot: dict, endpoint: str, encoder) -> bool:
    passages = validate_snapshot(snapshot)
    vectors = encoder.encode([passage["text"] for passage in passages])
    if len(vectors) != len(passages):
        raise ValueError("Missing semantic document vectors")
    points = [point_for(passage, vector) for passage, vector in zip(passages, vectors)]
    path = f"/collections/{COLLECTION}"
    collection = request_json(endpoint, "GET", path)
    if collection is None:
        request_json(endpoint, "PUT", path, {"vectors": {"size": DIMENSIONS, "distance": "Cosine"}})
    else:
        schema = collection["result"]["config"]["params"]["vectors"]
        if schema.get("size") != DIMENSIONS or schema.get("distance") != "Cosine":
            raise ValueError("Existing semantic source collection has a different schema")

    count = request_json(endpoint, "POST", f"{path}/points/count", {"exact": True})["result"]["count"]
    stored = request_json(endpoint, "POST", f"{path}/points", {
        "ids": [p["id"] for p in points], "with_payload": True, "with_vector": True,
    })["result"]
    if stored:
        if count != len(points) or len(stored) != len(points):
            raise ValueError("Partial semantic source collection; no points overwritten")
        expected = {p["id"]: p for p in points}
        for item in stored:
            wanted = expected.get(item["id"])
            if (wanted is None or item["payload"] != wanted["payload"]
                    or any(not math.isclose(a, b, abs_tol=1e-4)
                           for a, b in zip(unit_vector(item["vector"]), wanted["vector"]))):
                raise ValueError("Semantic source point differs; no points overwritten")
        changed = False
    else:
        if count:
            raise ValueError("Unknown semantic source points; no points overwritten")
        result = request_json(endpoint, "PUT", f"{path}/points?wait=true", {"points": points})
        if result["result"].get("status") != "completed":
            raise ValueError("Semantic source upsert did not complete")
        changed = True
    final = request_json(endpoint, "POST", f"{path}/points/count", {"exact": True})["result"]["count"]
    if final != len(points):
        raise ValueError("Semantic source collection has an unexpected count")
    return changed


def search(snapshot: dict, endpoint: str, query: str, tenant_id: str, encoder,
           top_k: int = 3) -> list[dict]:
    passages = validate_snapshot(snapshot)
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200:
        raise ValueError("Query must contain 1 to 200 characters")
    if type(top_k) is not int or not 1 <= top_k <= 10:
        raise ValueError("top_k must be 1 to 10")
    vectors = encoder.encode([query.strip()])
    if len(vectors) != 1:
        raise ValueError("Missing semantic query vector")
    filters = {"must": [
        {"key": "tenant_id", "match": {"value": tenant_id}},
        {"key": "document_id", "match": {"value": snapshot["document_id"]}},
        {"key": "document_version", "match": {"value": snapshot["document_version"]}},
        {"key": "source_sha256", "match": {"value": snapshot["source_sha256"]}},
    ]}
    results = request_json(endpoint, "POST", f"/collections/{COLLECTION}/points/query", {
        "query": unit_vector(vectors[0]), "filter": filters, "limit": top_k,
        "with_payload": True,
    })["result"]["points"]
    known = {p["id"]: p for p in passages}
    hits = []
    for result in results:
        passage = known.get(result["id"])
        if (passage is None or result["payload"] != source_payload(passage)
                or passage["tenant_id"] != tenant_id):
            raise ValueError("Semantic hit has no matching exported PostgreSQL source")
        hits.append({"source_id": result["id"], "clause": passage["clause"],
                     "score": result["score"], "retrieval_method": "qdrant_bge_small"})
    return hits
