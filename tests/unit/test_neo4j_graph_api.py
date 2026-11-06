"""Private graph API enforces token before any graph access."""

import os
import unittest
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.services.neo4j_graph_api import local_bolt_endpoint
from datasets.generator.seed_price_case import database_id


class Neo4jGraphApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.path = "/api/v1/graph/invoices/chain"
        self.token = "local-demo-secret-with-at-least-32-characters"
        self.tenant = database_id("DEMO-001", "TENANT")
        self.invoice = database_id("DEMO-001", "INV-001")
        self.body = {"tenant_id": str(self.tenant), "invoice_id": str(self.invoice)}
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.env = {"PROCUREGRAPH_ENABLE_DEMO_DB_API": "1",
                    "PROCUREGRAPH_DEMO_EVIDENCE_TOKEN": self.token,
                    "PROCUREGRAPH_NEO4J_BOLT": "bolt://127.0.0.1:7687",
                    "PROCUREGRAPH_NEO4J_PASSWORD": "secret"}

    def test_disabled_and_missing_token_never_touch_graph(self):
        with (patch.dict(os.environ, self.env, clear=True),
              patch("apps.api.app.main.read_checked_graph") as read):
            self.assertEqual(self.client.post(self.path, json=self.body).status_code, 401)
            self.assertEqual(self.client.post(self.path, json=self.body,
                                              headers={"Authorization": "Bearer wrong"}).status_code, 401)
            read.assert_not_called()
            os.environ["PROCUREGRAPH_ENABLE_DEMO_DB_API"] = "0"
            self.assertEqual(self.client.post(self.path, json=self.body,
                                              headers=self.headers).status_code, 404)
            read.assert_not_called()

    def test_success_and_other_tenant_are_bounded(self):
        node = {"label": "Invoice", "id": str(self.invoice), "tenant_id": str(self.tenant)}
        edge = {"id": str(UUID(int=1)), "type": "REFERENCES_PO",
                "from_id": str(self.invoice), "to_id": str(UUID(int=2)),
                "tenant_id": str(self.tenant), "source_type": "invoices",
                "source_id": str(self.invoice), "extraction_method": "checked_relational_fk",
                "created_at": "2026-11-06T12:00:00+00:00"}
        chain = {"tenant_id": str(self.tenant), "invoice_id": str(self.invoice),
                 "nodes": [node], "edges": [edge]}
        with (patch.dict(os.environ, self.env, clear=True),
              patch("apps.api.app.main.read_checked_graph",
                    side_effect=[chain, None]) as read):
            result = self.client.post(self.path, json=self.body, headers=self.headers)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["chain"]["edges"][0]["source_id"], str(self.invoice))
            self.assertEqual(read.call_args.args[:2], (self.tenant, self.invoice))
            other = self.client.post(self.path, json={**self.body, "tenant_id": str(UUID(int=0))},
                                     headers=self.headers)
            self.assertEqual(other.json(), {"chain": None})

    def test_conflict_and_unavailable_do_not_expose_details(self):
        with (patch.dict(os.environ, self.env, clear=True),
              patch("apps.api.app.main.read_checked_graph",
                    side_effect=ValueError("private mismatch"))):
            response = self.client.post(self.path, json=self.body, headers=self.headers)
            self.assertEqual(response.status_code, 409)
            self.assertNotIn("private mismatch", response.text)
        with (patch.dict(os.environ, self.env, clear=True),
              patch("apps.api.app.main.read_checked_graph",
                    side_effect=OSError("private connection"))):
            response = self.client.post(self.path, json=self.body, headers=self.headers)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("private connection", response.text)

    def test_only_loopback_bolt_is_accepted(self):
        self.assertEqual(local_bolt_endpoint("bolt://127.0.0.1:7687"), "bolt://127.0.0.1:7687")
        for endpoint in ("bolt://example.com:7687", "bolt://localhost:7687",
                         "bolt://127.0.0.1:7687/path", "http://127.0.0.1:7687"):
            with self.subTest(endpoint=endpoint), self.assertRaises(OSError):
                local_bolt_endpoint(endpoint)


if __name__ == "__main__":
    unittest.main()
