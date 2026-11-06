"""Live private read of the retained synthetic investigation records."""

import os
import secrets
from decimal import Decimal
from uuid import UUID

import psycopg
from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.services.contract_evidence import EXPECTED_SHA256
from datasets.generator.seed_price_case import database_id


def lookup(connection, tenant: UUID, key: str) -> UUID:
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id FROM investigations
            WHERE tenant_id = %s AND idempotency_key = %s
        """, (tenant, key))
        row = cursor.fetchone()
    if row is None:
        raise LookupError("Run the persisted finding check before this read check")
    return row[0]


def main() -> None:
    tenant = database_id("DEMO-001", "TENANT")
    with psycopg.connect(
        host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
        dbname="procuregraph", user="postgres", password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
    ) as connection:
        finding_id = lookup(connection, tenant, "demo-verified-price-investigation-v1")
        abstention_id = lookup(connection, tenant, "demo-investigation-abstention-v1")
    os.environ["PROCUREGRAPH_ENABLE_DEMO_DB_API"] = "1"
    os.environ["PROCUREGRAPH_DEMO_EVIDENCE_TOKEN"] = secrets.token_urlsafe(32)
    client = TestClient(app)
    params = {"tenant_id": str(tenant)}
    path = f"/api/v1/investigations/{finding_id}"
    if client.get(path, params=params).status_code != 401:
        raise AssertionError("Missing token was not denied")
    headers = {"Authorization": f"Bearer {os.environ['PROCUREGRAPH_DEMO_EVIDENCE_TOKEN']}"}
    response = client.get(path, params=params, headers=headers)
    if response.status_code != 200:
        raise AssertionError(response.text)
    record = response.json()
    finding = record["finding"]
    if (record["status"] != "needs_review" or record["id"] != str(finding_id)
            or finding["document_sha256"] != EXPECTED_SHA256
            or Decimal(finding["excess_amount"]) != Decimal("10.00")
            or finding["clauses"] != ["2.1", "2.2", "2.3"]
            or len(finding["graph_edge_ids"]) != 4):
        raise AssertionError("Stored finding API source differs")
    print("PASS: token-protected investigation API returned saved INR 10.00 finding and citations")
    other = client.get(path, params={"tenant_id": str(UUID(int=0))}, headers=headers)
    if other.status_code != 404:
        raise AssertionError("Another tenant read the stored finding")
    abstained = client.get(f"/api/v1/investigations/{abstention_id}",
                           params=params, headers=headers)
    if (abstained.status_code != 200 or abstained.json()["status"] != "abstained"
            or abstained.json()["finding"] is not None):
        raise AssertionError("Stored abstention API differs")
    print("PASS: missing token denied; another tenant saw no finding; abstention had no citation")
    queue_path = "/api/v1/review/queue"
    if client.get(queue_path, params=params).status_code != 401:
        raise AssertionError("Review queue accepted a missing token")
    queue = client.get(queue_path, params={**params, "limit": 1}, headers=headers)
    if queue.status_code != 200:
        raise AssertionError(queue.text)
    items = queue.json()["items"]
    if (len(items) != 1 or items[0]["id"] != str(finding_id)
            or items[0]["status"] != "needs_review"
            or Decimal(items[0]["excess_amount"]) != Decimal("10.00")):
        raise AssertionError("Review queue did not contain the saved finding")
    other_queue = client.get(queue_path, params={"tenant_id": str(UUID(int=0))},
                             headers=headers)
    if other_queue.status_code != 200 or other_queue.json() != {"items": []}:
        raise AssertionError("Another tenant saw the review queue")
    if client.get(queue_path, params={**params, "limit": 21}, headers=headers).status_code != 422:
        raise AssertionError("Unbounded review queue request was accepted")
    print("PASS: bounded review queue returned the saved finding, no abstention or other-tenant rows")


if __name__ == "__main__":
    main()
