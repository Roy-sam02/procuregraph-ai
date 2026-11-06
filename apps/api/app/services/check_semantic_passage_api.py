"""Live semantic API check against saved PostgreSQL and Qdrant volumes."""

import os
import secrets

from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.services.contract_evidence import EXPECTED_SHA256
from datasets.generator.seed_price_case import database_id


def check() -> None:
    client = TestClient(app)
    path = "/api/v1/evidence/passages/search"
    os.environ["PROCUREGRAPH_ENABLE_DEMO_DB_API"] = "1"
    os.environ["PROCUREGRAPH_DEMO_EVIDENCE_TOKEN"] = secrets.token_urlsafe(32)
    request = {"tenant_id": str(database_id("DEMO-001", "TENANT")),
               "query": "price tolerance above allowed", "top_k": 1,
               "retrieval_method": "qdrant_bge_small"}
    denied = client.post(path, json=request)
    assert denied.status_code == 401, denied.text
    headers = {"Authorization": f"Bearer {os.environ['PROCUREGRAPH_DEMO_EVIDENCE_TOKEN']}"}
    response = client.post(path, json=request, headers=headers)
    assert response.status_code == 200, response.text
    hits = response.json()["hits"]
    assert len(hits) == 1 and hits[0]["clause"] == "2.2", hits
    assert hits[0]["source_sha256"] == EXPECTED_SHA256, hits
    assert hits[0]["document_id"] == str(database_id("DEMO-001", "CON-001/document/v1")), hits
    assert hits[0]["retrieval_method"] == "qdrant_bge_small" and hits[0]["snippet"], hits
    lexical = client.post(path, json={**request, "retrieval_method": "postgres_fts"}, headers=headers)
    assert lexical.status_code == 200 and lexical.json()["hits"][0]["source_id"] == hits[0]["source_id"], lexical.text
    print("PASS: semantic API matched Qdrant clause 2.2 to the current PostgreSQL source and lexical result")

    other = client.post(path, json={**request, "tenant_id": str(database_id("OTHER", "TENANT"))},
                        headers=headers)
    assert other.status_code == 200 and other.json() == {"hits": []}, other.text
    print("PASS: missing token was denied and another tenant got no semantic hits")


if __name__ == "__main__":
    check()
