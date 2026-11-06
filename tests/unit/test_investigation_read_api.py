"""Private reads reject missing tokens and cross-tenant or conflicting records."""

import os
import unittest
from dataclasses import asdict
from unittest.mock import patch
from uuid import UUID

from fastapi.testclient import TestClient

from apps.api.app.main import app
from tests.unit import test_price_evidence_verifier as source_tests


class InvestigationReadApiTests(unittest.TestCase):
    def setUp(self):
        fixture = source_tests.PriceEvidenceVerifierTests()
        fixture.setUp()
        self.f = fixture
        self.client = TestClient(app)
        self.investigation = UUID(int=5)
        self.path = f"/api/v1/investigations/{self.investigation}"
        self.params = {"tenant_id": str(fixture.tenant)}
        self.token = "demo-record-token-with-at-least-32-characters"
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.env = {"PROCUREGRAPH_ENABLE_DEMO_DB_API": "1",
                    "PROCUREGRAPH_DEMO_EVIDENCE_TOKEN": self.token,
                    "PROCUREGRAPH_DB_PORT": "5432", "PROCUREGRAPH_DB_PASSWORD": "local-test"}
        self.saved = {
            "id": str(self.investigation), "tenant_id": str(fixture.tenant),
            "invoice_id": str(fixture.invoice), "invoice_line_id": str(fixture.id("IL-001")),
            "created_by": "local-check", "status": "needs_review", "error_code": None,
            "created_at": "2026-11-07T00:00:00+00:00", "finding_id": str(UUID(int=6)),
            "finding": asdict(fixture.verify()),
        }

    def test_token_and_feature_flag_checked_before_database(self):
        with (patch.dict(os.environ, self.env, clear=True),
              patch("apps.api.app.main.read_investigation") as read,
              patch("apps.api.app.main.psycopg.connect") as connect):
            self.assertEqual(self.client.get(self.path, params=self.params).status_code, 401)
            self.assertEqual(self.client.get(self.path, params=self.params,
                                             headers={"Authorization": "Bearer wrong"}).status_code, 401)
            os.environ["PROCUREGRAPH_ENABLE_DEMO_DB_API"] = "0"
            self.assertEqual(self.client.get(self.path, params=self.params,
                                             headers=self.headers).status_code, 404)
            read.assert_not_called()
            connect.assert_not_called()

    def test_verified_finding_is_returned_and_tenant_is_passed_to_query(self):
        with (patch.dict(os.environ, self.env, clear=True),
              patch("apps.api.app.main.psycopg.connect"),
              patch("apps.api.app.main.read_investigation", return_value=self.saved) as read):
            response = self.client.get(self.path, params=self.params, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["finding"]["excess_amount"], "10.00")
        self.assertEqual(len(response.json()["finding"]["graph_edge_ids"]), 4)
        self.assertEqual(read.call_args.args[1:], (self.f.tenant, self.investigation))

    def test_wrong_tenant_is_not_found(self):
        with (patch.dict(os.environ, self.env, clear=True),
              patch("apps.api.app.main.psycopg.connect"),
              patch("apps.api.app.main.read_investigation", return_value=None) as read):
            response = self.client.get(self.path, params={"tenant_id": str(UUID(int=0))},
                                       headers=self.headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(read.call_args.args[1], UUID(int=0))

    def test_corrupt_record_is_not_served(self):
        broken = {**self.saved, "finding": {**self.saved["finding"],
                                            "document_sha256": None}}
        with (patch.dict(os.environ, self.env, clear=True),
              patch("apps.api.app.main.psycopg.connect"),
              patch("apps.api.app.main.read_investigation", return_value=broken)):
            response = self.client.get(self.path, params=self.params, headers=self.headers)
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
