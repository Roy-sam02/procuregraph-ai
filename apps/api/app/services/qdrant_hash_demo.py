"""Local Qdrant wiring with deterministic lexical hash vectors, not semantic embeddings."""

import hashlib
import json
import math
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, uuid5

from apps.api.app.services.contract_evidence import EXPECTED_SHA256
from apps.api.app.services.hash_vectors import DIMENSIONS, MODEL_ID, embed
from datasets.generator.seed_price_case import database_id

COLLECTION = "procuregraph_synthetic_hash_v1"


def local_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port is None
            or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise ValueError("Qdrant must be a loopback HTTP origin")
    return endpoint


def request_json(endpoint: str, method: str, path: str, body: dict | None = None) -> dict | None:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(local_endpoint(endpoint) + path, data=data, method=method,
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=8) as response:
            result = json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if result.get("status") != "ok":
        raise ValueError("Qdrant operation did not succeed")
    return result


def validate_snapshot(snapshot: dict) -> list[dict]:
    if (snapshot.get("schema_version") != 1 or snapshot.get("vectorizer") != MODEL_ID
            or snapshot.get("tenant_id") != str(database_id("DEMO-001", "TENANT"))
            or snapshot.get("document_id") != str(database_id("DEMO-001", "CON-001/document/v1"))
            or snapshot.get("document_version") != 1
            or snapshot.get("source_sha256") != EXPECTED_SHA256):
        raise ValueError("Unexpected vector snapshot source or model")
    passages = snapshot.get("passages")
    if not isinstance(passages, list) or len(passages) != 3:
        raise ValueError("Expected three source-linked passages")
    for passage, clause in zip(passages, ("2.1", "2.2", "2.3")):
        if (passage.get("tenant_id") != snapshot["tenant_id"]
                or passage.get("document_id") != snapshot["document_id"]
                or passage.get("document_version") != snapshot["document_version"]
                or passage.get("source_sha256") != snapshot["source_sha256"]
                or passage.get("clause") != clause or passage.get("page") != 1
                or not isinstance(passage.get("text"), str)):
            raise ValueError("Passage provenance disagrees with snapshot")
        text_hash = hashlib.sha256(passage["text"].encode("utf-8")).hexdigest()
        if text_hash != passage.get("text_hash"):
            raise ValueError("Passage text hash differs")
        identity = (f"{passage['tenant_id']}/{passage['document_id']}/"
                    f"{passage['document_version']}/{passage['source_sha256']}/"
                    f"{passage['page']}/{clause}/{passage['start_offset']}/"
                    f"{passage['end_offset']}/{text_hash}")
        if passage.get("id") != str(uuid5(NAMESPACE_URL, f"procuregraph/chunk/{identity}")):
            raise ValueError("Passage ID differs from its source and offsets")
    return passages


def point_for(passage: dict) -> dict:
    return {"id": passage["id"], "vector": embed(passage["text"]), "payload": {
        "tenant_id": passage["tenant_id"], "document_id": passage["document_id"],
        "document_version": passage["document_version"], "source_sha256": passage["source_sha256"],
        "clause": passage["clause"], "text_hash": passage["text_hash"],
        "vectorizer": MODEL_ID,
    }}


def index_snapshot(snapshot: dict, endpoint: str) -> bool:
    points = [point_for(p) for p in validate_snapshot(snapshot)]
    path = f"/collections/{COLLECTION}"
    collection = request_json(endpoint, "GET", path)
    if collection is None:
        request_json(endpoint, "PUT", path, {"vectors": {"size": DIMENSIONS, "distance": "Cosine"}})
    else:
        vectors = collection["result"]["config"]["params"]["vectors"]
        if vectors.get("size") != DIMENSIONS or vectors.get("distance") != "Cosine":
            raise ValueError("Existing Qdrant collection has a different vector schema")

    count_before = request_json(endpoint, "POST", f"{path}/points/count", {
        "exact": True,
    })["result"]["count"]
    if count_before not in (0, 3):
        raise ValueError("Unexpected Qdrant point count; no points overwritten")

    existing = request_json(endpoint, "POST", f"{path}/points", {
        "ids": [p["id"] for p in points], "with_payload": True, "with_vector": True,
    })["result"]
    if existing:
        if count_before != 3 or len(existing) != len(points):
            raise ValueError("Partial existing Qdrant index; no points overwritten")
        expected = {p["id"]: p for p in points}
        for stored in existing:
            point = expected.get(stored["id"])
            if (point is None or stored["payload"] != point["payload"]
                    or len(stored["vector"]) != DIMENSIONS
                    or any(not math.isclose(a, b, abs_tol=1e-5)
                           for a, b in zip(stored["vector"], point["vector"]))):
                raise ValueError("Existing Qdrant point differs; no points overwritten")
        changed = False
    else:
        if count_before != 0:
            raise ValueError("Qdrant collection contains unknown points; no points overwritten")
        response = request_json(endpoint, "PUT", f"{path}/points?wait=true", {"points": points})
        if response["result"].get("status") != "completed":
            raise ValueError("Qdrant upsert was not completed")
        changed = True
    count = request_json(endpoint, "POST", f"{path}/points/count", {"exact": True})["result"]["count"]
    if count != 3:
        raise ValueError("Expected exactly three points in the synthetic collection")
    return changed


def search(snapshot: dict, endpoint: str, query: str, tenant_id: str, top_k: int = 3) -> list[dict]:
    passages = validate_snapshot(snapshot)
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 200:
        raise ValueError("Query must contain 1 to 200 characters")
    if type(top_k) is not int or not 1 <= top_k <= 10:
        raise ValueError("top_k must be 1 to 10")
    filters = {"must": [
        {"key": "tenant_id", "match": {"value": tenant_id}},
        {"key": "document_id", "match": {"value": snapshot["document_id"]}},
        {"key": "document_version", "match": {"value": snapshot["document_version"]}},
    ]}
    result = request_json(endpoint, "POST", f"/collections/{COLLECTION}/points/query", {
        "query": embed(query), "filter": filters, "limit": top_k, "with_payload": True,
    })["result"]["points"]
    known = {p["id"]: p for p in passages}
    hits = []
    for point in result:
        source = known.get(point["id"])
        if (source is None or point["payload"] != point_for(source)["payload"]
                or point["payload"]["tenant_id"] != tenant_id):
            raise ValueError("Qdrant hit has no matching PostgreSQL-exported source")
        hits.append({"source_id": point["id"], "clause": source["clause"],
                     "score": point["score"], "retrieval_method": "qdrant_hash_demo"})
    return hits
