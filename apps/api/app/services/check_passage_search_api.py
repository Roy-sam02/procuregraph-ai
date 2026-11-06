"""Exercise the private search API against saved PostgreSQL chunks."""

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
    tenant_id = str(database_id("DEMO-001", "TENANT"))
    request = {"tenant_id": tenant_id, "query": "tolerance", "top_k": 1}
    denied = client.post(path, json=request)
    wrong = client.post(path, json=request, headers={"Authorization": "Bearer incorrect"})
    assert denied.status_code == wrong.status_code == 401, (denied.text, wrong.text)
    headers = {"Authorization": f"Bearer {os.environ['PROCUREGRAPH_DEMO_EVIDENCE_TOKEN']}"}
    response = client.post(path, json=request, headers=headers)
    assert response.status_code == 200, response.text
    hits = response.json()["hits"]
    assert len(hits) == 1, hits
    assert hits[0]["clause"] == "2.2" and hits[0]["source_sha256"] == EXPECTED_SHA256, hits
    assert hits[0]["document_id"] == str(database_id("DEMO-001", "CON-001/document/v1")), hits
    assert hits[0]["retrieval_method"] == "postgres_fts", hits
    print("PASS: private API returned the source-linked PostgreSQL clause 2.2")

    other = client.post(path, json={**request, "tenant_id": str(database_id("OTHER", "TENANT"))},
                        headers=headers)
    assert other.status_code == 200 and other.json() == {"hits": []}, other.text
    invalid = client.post(path, json={**request, "top_k": 11}, headers=headers)
    assert invalid.status_code == 422, invalid.text
    print("PASS: missing and wrong tokens were denied; other tenant got no hits; invalid limit rejected")


if __name__ == "__main__":
    check()
