"""The demo search route enforces its token and tenant boundary."""

import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.services.contract_evidence import EXPECTED_SHA256
from datasets.generator.seed_price_case import database_id


class PassageSearchApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.path = "/api/v1/evidence/passages/search"
        self.token = "local-demo-secret-with-at-least-32-characters"
        self.request = {"tenant_id": str(database_id("DEMO-001", "TENANT")),
                        "query": "tolerance", "top_k": 1}
        self.settings = {"PROCUREGRAPH_ENABLE_DEMO_DB_API": "1",
                         "PROCUREGRAPH_DEMO_EVIDENCE_TOKEN": self.token,
                         "PROCUREGRAPH_DB_PORT": "5432",
                         "PROCUREGRAPH_DB_PASSWORD": "test-password"}

    def test_disabled_missing_and_wrong_token_never_query_database(self):
        with (patch.dict(os.environ, self.settings, clear=True),
              patch("apps.api.app.main.psycopg.connect") as connect):
            for headers in ({}, {"Authorization": "Bearer wrong"}):
                result = self.client.post(self.path, json=self.request, headers=headers)
                self.assertEqual(result.status_code, 401)
                self.assertEqual(result.headers["WWW-Authenticate"], "Bearer")
            connect.assert_not_called()
            os.environ["PROCUREGRAPH_ENABLE_DEMO_DB_API"] = "0"
            self.assertEqual(self.client.post(self.path, json=self.request).status_code, 404)
            connect.assert_not_called()

    def test_valid_query_returns_bounded_source_linked_hits(self):
        hit = {"source_id": str(database_id("DEMO-001", "chunk")),
               "document_id": str(database_id("DEMO-001", "CON-001/document/v1")),
               "document_version": 1, "page": 1, "clause": "2.2",
               "start_offset": 100, "end_offset": 200,
               "source_sha256": EXPECTED_SHA256, "text_hash": "a" * 64,
               "snippet": "Price tolerance five percent", "retrieval_method": "postgres_fts",
               "score": 0.5}
        connection = MagicMock()
        connection.__enter__.return_value = connection
        headers = {"Authorization": f"Bearer {self.token}"}
        with (patch.dict(os.environ, self.settings, clear=True),
              patch("apps.api.app.main.psycopg.connect", return_value=connection),
              patch("apps.api.app.main.search_passages", return_value=[hit]) as search):
            result = self.client.post(self.path, json=self.request, headers=headers)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json(), {"hits": [hit]})
            self.assertEqual(search.call_args.args[1:],
                             (database_id("DEMO-001", "TENANT"), "tolerance", 1))

            for changes in ({"query": " "}, {"query": "a" * 201},
                            {"top_k": 11}, {"top_k": 0}, {"top_k": "2"}):
                result = self.client.post(self.path, json={**self.request, **changes},
                                          headers=headers)
                self.assertEqual(result.status_code, 422, result.text)
            self.assertEqual(search.call_count, 1)

    def test_database_failure_is_not_exposed(self):
        import psycopg

        with (patch.dict(os.environ, self.settings, clear=True),
              patch("apps.api.app.main.psycopg.connect",
                    side_effect=psycopg.OperationalError("private details"))):
            result = self.client.post(self.path, json=self.request, headers={
                "Authorization": f"Bearer {self.token}"})
            self.assertEqual(result.status_code, 503)
            self.assertNotIn("private details", result.text)


if __name__ == "__main__":
    unittest.main()
