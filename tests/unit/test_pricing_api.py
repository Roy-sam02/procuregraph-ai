import unittest

from fastapi.testclient import TestClient

from apps.api.app.main import app


class PricingApiTests(unittest.TestCase):
    def test_above_and_at_limit(self):
        client = TestClient(app)
        request = {
            "contract_price": "100",
            "tolerance_percent": "5",
            "invoice_price": "106",
        }

        above = client.post("/api/v1/pricing/check", json=request)
        self.assertEqual(above.status_code, 200)
        self.assertEqual(above.json(), {"is_violation": True})

        request["invoice_price"] = "105"
        at_limit = client.post("/api/v1/pricing/check", json=request)
        self.assertEqual(at_limit.status_code, 200)
        self.assertEqual(at_limit.json(), {"is_violation": False})

    def test_rejects_negative_contract_price(self):
        client = TestClient(app)
        response = client.post(
            "/api/v1/pricing/check",
            json={
                "contract_price": "-100",
                "tolerance_percent": "5",
                "invoice_price": "106",
            },
        )
        self.assertEqual(response.status_code, 422)