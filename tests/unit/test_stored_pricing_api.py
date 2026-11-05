import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from apps.api.app.main import app


class StoredPricingApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.request = {
            "tenant_id": "00000000-0000-0000-0000-000000000010",
            "invoice_line_id": "00000000-0000-0000-0000-000000000801",
        }

    def test_demo_endpoint_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.post(
                "/api/v1/pricing/cases/assess", json=self.request
            )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")

    def test_request_requires_uuid_identifiers(self):
        with patch.dict(os.environ, {"PROCUREGRAPH_ENABLE_DEMO_DB_API": "1"}):
            response = self.client.post(
                "/api/v1/pricing/cases/assess",
                json={"tenant_id": "not-a-uuid", "invoice_line_id": "also-invalid"},
            )
        self.assertEqual(response.status_code, 422)

    def test_existing_calculator_contract_still_works(self):
        response = self.client.post(
            "/api/v1/pricing/check",
            json={
                "contract_price": "100",
                "tolerance_percent": "5",
                "invoice_price": "106",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"is_violation": True})


if __name__ == "__main__":
    unittest.main()
