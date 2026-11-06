"""Test the real review API against PostgreSQL without retaining a decision."""

import hashlib
import json
import os
import secrets
from contextlib import nullcontext
from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
from fastapi.testclient import TestClient

from apps.api.app.agents.investigation_records import read_review_queue
from apps.api.app.main import app
from datasets.generator.seed_price_case import database_id


class RollBackCheck(Exception):
    pass


def main() -> None:
    tenant = database_id("DEMO-001", "TENANT")
    actor = uuid4()
    reviewer_token, read_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    config = json.dumps({"tenant_id": str(tenant), "reviewer_id": str(actor),
                         "token_sha256": hashlib.sha256(reviewer_token.encode()).hexdigest()})
    env = {"PROCUREGRAPH_ENABLE_DEMO_DB_API": "1",
           "PROCUREGRAPH_DEMO_REVIEWER": config,
           "PROCUREGRAPH_DEMO_EVIDENCE_TOKEN": read_token}
    try:
        with psycopg.connect(host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
                             dbname="procuregraph", user="postgres",
                             password=os.environ["PROCUREGRAPH_DB_PASSWORD"]) as connection:
            with connection.transaction():
                queue = read_review_queue(connection, tenant)
                if len(queue) != 1:
                    raise ValueError("Expected exactly one synthetic finding")
                finding = UUID(queue[0]["finding_id"])
                path = f"/api/v1/review/findings/{finding}/decision"
                body = {"tenant_id": str(tenant), "decision": "rejected",
                        "reason": "Synthetic contract check"}
                headers = {"Authorization": f"Bearer {reviewer_token}",
                           "Idempotency-Key": "local-api-review-0001"}
                with patch.dict(os.environ, env), patch(
                    "apps.api.app.main.psycopg.connect", return_value=nullcontext(connection)
                ), TestClient(app) as client:
                    if client.post(path, json=body, headers={
                        "Idempotency-Key": "local-api-review-0001"
                    }).status_code != 401:
                        raise ValueError("Unauthenticated decision was accepted")
                    other = {**body, "tenant_id": str(UUID(int=0))}
                    if client.post(path, json=other, headers=headers).status_code != 403:
                        raise ValueError("Other tenant decision was accepted")
                    result = client.post(path, json=body, headers=headers)
                    if result.status_code != 200 or result.json()["actor_id"] != str(actor):
                        raise ValueError(f"Reviewer decision failed with HTTP {result.status_code}")
                    again = client.post(path, json=body, headers=headers)
                    if again.status_code != 200 or again.json()["id"] != result.json()["id"]:
                        raise ValueError("Review API retry returned a different decision")
                    if client.post(path, json={**body, "decision": "approved"},
                                   headers=headers).status_code != 409:
                        raise ValueError("Conflicting review decision was accepted")
                if read_review_queue(connection, tenant):
                    raise ValueError("Decided finding remained in queue")
                with connection.cursor() as cursor:
                    cursor.execute("SELECT actor_id, created_at FROM approvals WHERE id = %s",
                                   (UUID(result.json()["id"]),))
                    saved_actor, saved_time = cursor.fetchone()
                    if saved_actor != actor or saved_time.tzinfo is None:
                        raise ValueError("Reviewer identity or server timestamp was not saved")
                raise RollBackCheck
    except RollBackCheck:
        pass
    print("PASS: review API identity, tenant, retry, conflict and timestamp; transaction rolled back")


if __name__ == "__main__":
    main()
