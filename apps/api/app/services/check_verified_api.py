"""Exercise the real API route against the saved synthetic PostgreSQL and MinIO volumes."""

import os
from decimal import Decimal

from fastapi.testclient import TestClient

from apps.api.app.main import app
from datasets.generator.seed_price_case import database_id


def check() -> None:
    client = TestClient(app)
    request = {
        "tenant_id": str(database_id("DEMO-001", "TENANT")),
        "invoice_line_id": str(database_id("DEMO-001", "IL-001")),
        "include_verified_evidence": True,
    }
    os.environ["PROCUREGRAPH_ENABLE_DEMO_DB_API"] = "1"
    response = client.post("/api/v1/pricing/cases/assess", json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    assert (Decimal(result["allowed_unit_price"]) == Decimal("105.00")
            and Decimal(result["excess_amount"]) == Decimal("10.00")), result
    source = result["evidence_reference"]
    assert source["document_id"] == str(database_id("DEMO-001", "CON-001/document/v1")), source
    assert source["document_version"] == 1 and source["page"] == 1, source
    assert (source["price_clause"], source["tolerance_clause"], source["dates_clause"]) == (
        "2.1", "2.2", "2.3"
    ), source
    print("PASS: live API verified document v1 from MinIO before returning its source reference")

    plain = client.post("/api/v1/pricing/cases/assess", json={**request, "include_verified_evidence": False})
    assert plain.status_code == 200 and "evidence_reference" not in plain.json(), plain.text
    other = client.post("/api/v1/pricing/cases/assess", json={
        **request, "tenant_id": str(database_id("OTHER", "TENANT")),
    })
    assert other.status_code == 404 and "evidence_reference" not in other.json(), other.text
    print("PASS: plain assessment has no citation and a different tenant gets no source")


if __name__ == "__main__":
    check()
