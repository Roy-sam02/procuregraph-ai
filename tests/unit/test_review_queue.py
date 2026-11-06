"""Review queue is bounded, tenant-filtered, and gated before database reads."""

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID

from fastapi.testclient import TestClient

from apps.api.app.agents.investigation_records import read_review_queue
from apps.api.app.main import app
from datasets.generator.seed_price_case import database_id


class ReviewQueueTests(unittest.TestCase):
    def setUp(self):
        self.tenant = database_id("DEMO-001", "TENANT")
        self.client = TestClient(app)
        self.path = "/api/v1/review/queue"
        self.token = "demo-review-token-with-at-least-32-characters"
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.env = {"PROCUREGRAPH_ENABLE_DEMO_DB_API": "1",
                    "PROCUREGRAPH_DEMO_EVIDENCE_TOKEN": self.token,
                    "PROCUREGRAPH_DB_PORT": "5432", "PROCUREGRAPH_DB_PASSWORD": "local-test"}
        self.item = {"id": str(UUID(int=5)), "invoice_id": str(UUID(int=6)),
                     "invoice_line_id": str(UUID(int=7)),
                     "created_at": "2026-11-07T00:00:00+00:00",
                     "finding_id": str(UUID(int=8)), "rule_id": "CONTRACT_UNIT_PRICE_VIOLATION",
                     "currency": "INR", "excess_amount": "10.00", "status": "needs_review"}

    def test_db_query_applies_tenant_status_and_limit(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            (UUID(int=5), UUID(int=6), UUID(int=7),
             datetime(2026, 11, 7, tzinfo=timezone.utc), UUID(int=8),
             "CONTRACT_UNIT_PRICE_VIOLATION", "INR", "10.00"),
        ]
        self.assertEqual(read_review_queue(connection, self.tenant, 1)[0], self.item)
        query, args = cursor.execute.call_args.args
        self.assertIn("i.tenant_id = %s", query)
        self.assertIn("i.status = 'needs_review'", query)
        self.assertIn("f.is_violation = TRUE", query)
        self.assertIn("LEFT JOIN approvals a", query)
        self.assertIn("a.id IS NULL", query)
        self.assertEqual(args, (self.tenant, 1))
        for limit in (0, 21, True):
            with self.assertRaises(ValueError):
                read_review_queue(connection, self.tenant, limit)

    def test_token_denial_and_disabled_gate_precede_database(self):
        with (patch.dict(os.environ, self.env, clear=True),
              patch("apps.api.app.main.psycopg.connect") as connect):
            self.assertEqual(self.client.get(self.path, params={"tenant_id": str(self.tenant)}).status_code, 401)
            os.environ["PROCUREGRAPH_ENABLE_DEMO_DB_API"] = "0"
            self.assertEqual(self.client.get(self.path, params={"tenant_id": str(self.tenant)},
                                             headers=self.headers).status_code, 404)
            connect.assert_not_called()

    def test_bounded_queue_and_other_tenant_empty(self):
        with (patch.dict(os.environ, self.env, clear=True),
              patch("apps.api.app.main.psycopg.connect"),
              patch("apps.api.app.main.read_review_queue",
                    side_effect=[[self.item], []]) as read):
            result = self.client.get(self.path, params={"tenant_id": str(self.tenant), "limit": 1},
                                     headers=self.headers)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json(), {"items": [self.item]})
            self.assertEqual(read.call_args.args[1:], (self.tenant, 1))
            other = self.client.get(self.path, params={"tenant_id": str(UUID(int=0))},
                                    headers=self.headers)
            self.assertEqual(other.json(), {"items": []})
            self.assertEqual(read.call_args.args[1], UUID(int=0))
            self.assertEqual(self.client.get(self.path, params={"tenant_id": str(self.tenant),
                                                            "limit": 21}, headers=self.headers).status_code, 422)

    def test_malformed_saved_queue_is_not_served(self):
        with (patch.dict(os.environ, self.env, clear=True),
              patch("apps.api.app.main.psycopg.connect"),
              patch("apps.api.app.main.read_review_queue",
                    return_value=[{**self.item, "excess_amount": None}])):
            response = self.client.get(self.path, params={"tenant_id": str(self.tenant)},
                                       headers=self.headers)
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
