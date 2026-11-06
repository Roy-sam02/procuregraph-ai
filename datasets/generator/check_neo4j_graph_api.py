"""Live token and tenant checks for the private invoice graph API."""

import os
import secrets
from uuid import UUID

from fastapi.testclient import TestClient

from apps.api.app.main import app
from datasets.generator.seed_price_case import database_id


def main() -> None:
    os.environ["PROCUREGRAPH_ENABLE_DEMO_DB_API"] = "1"
    os.environ["PROCUREGRAPH_DEMO_EVIDENCE_TOKEN"] = secrets.token_urlsafe(32)
    client = TestClient(app)
    path = "/api/v1/graph/invoices/chain"
    invoice = str(database_id("DEMO-001", "INV-001"))
    request = {"tenant_id": str(database_id("DEMO-001", "TENANT")), "invoice_id": invoice}
    missing = client.post(path, json=request)
    assert missing.status_code == 401, missing.text
    headers = {"Authorization": f"Bearer {os.environ['PROCUREGRAPH_DEMO_EVIDENCE_TOKEN']}"}
    response = client.post(path, json=request, headers=headers)
    assert response.status_code == 200, response.text
    chain = response.json()["chain"]
    assert chain["invoice_id"] == invoice and len(chain["nodes"]) == 4, chain
    assert len(chain["edges"]) == 4 and all(
        edge["source_id"] and edge["source_type"] and edge["created_at"]
        for edge in chain["edges"]
    ), chain
    print("PASS: token-protected graph API returned four manifest-checked source edges")

    other = client.post(path, json={**request, "tenant_id": str(UUID(int=0))}, headers=headers)
    assert other.status_code == 200 and other.json() == {"chain": None}, other.text
    print("PASS: missing token denied; another tenant received no graph chain")


if __name__ == "__main__":
    main()
