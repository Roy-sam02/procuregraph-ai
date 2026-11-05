import unittest

from fastapi.testclient import TestClient

from apps.api.app.main import app


class HealthEndpointTests(unittest.TestCase):
    def test_live_endpoint(self):
        client = TestClient(app)
        response = client.get("/health/live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})