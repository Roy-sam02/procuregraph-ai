import os
import unittest
from unittest.mock import MagicMock, patch
from uuid import UUID

from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.services.contract_evidence import EXPECTED_SHA256
from apps.api.app.services.qdrant_semantic_sources import source_payload
from datasets.generator.seed_price_case import database_id


class SemanticPassageSearchApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.token = "local-demo-secret-with-at-least-32-characters"
        self.tenant = database_id("DEMO-001", "TENANT")
        self.source = database_id("DEMO-001", "chunk")
        self.document = database_id("DEMO-001", "CON-001/document/v1")
        self.body = {"tenant_id": str(self.tenant), "query": "Is the cost too high?",
                     "top_k": 1, "retrieval_method": "qdrant_bge_small"}
        self.env = {"PROCUREGRAPH_ENABLE_DEMO_DB_API": "1",
                    "PROCUREGRAPH_DEMO_EVIDENCE_TOKEN": self.token,
                    "PROCUREGRAPH_DB_PORT": "5432", "PROCUREGRAPH_DB_PASSWORD": "secret",
                    "PROCUREGRAPH_QDRANT_ENDPOINT": "http://127.0.0.1:6333"}
        self.row = (self.source, self.document, 1, 1, "2.2", 100, 200,
                    EXPECTED_SHA256, "a" * 64, "Clause 2.2 price tolerance")
        self.point = {"id": str(self.source), "score": 0.87, "payload": source_payload({
            "tenant_id": str(self.tenant), "document_id": str(self.document),
            "document_version": 1, "page": 1, "clause": "2.2",
            "start_offset": 100, "end_offset": 200,
            "source_sha256": EXPECTED_SHA256, "text_hash": "a" * 64,
        })}
        self.connection = MagicMock()
        self.connection.__enter__.return_value = self.connection
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.cursor.fetchall.return_value = [self.row]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_token_denied_before_model_and_sources(self):
        with (patch.dict(os.environ, self.env, clear=True),
              patch("apps.api.app.main.LocalEncoder") as encoder,
              patch("apps.api.app.main.psycopg.connect") as connect):
            result = self.client.post("/api/v1/evidence/passages/search", json=self.body)
            self.assertEqual(result.status_code, 401)
            encoder.assert_not_called()
            connect.assert_not_called()

    def test_semantic_hit_must_match_current_tenant_source_and_payload(self):
        fake_encoder = MagicMock()
        fake_encoder.encode.return_value = [[1.0] + [0.0] * 383]
        with (patch.dict(os.environ, self.env, clear=True),
              patch("apps.api.app.main.LocalEncoder", return_value=fake_encoder),
              patch("apps.api.app.main.psycopg.connect", return_value=self.connection),
              patch("apps.api.app.services.semantic_passage_search.request_json",
                    return_value={"result": {"points": [self.point]}}) as query):
            result = self.client.post("/api/v1/evidence/passages/search", json=self.body,
                                      headers=self.headers)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["hits"][0]["snippet"], self.row[9])
            self.assertEqual(query.call_args.args[3]["filter"]["must"][0]["match"]["value"],
                             str(self.tenant))
            self.assertEqual(self.cursor.execute.call_args.args[1],
                             (self.tenant, self.tenant, [self.source]))
            self.cursor.fetchall.return_value = []
            stale = self.client.post("/api/v1/evidence/passages/search", json=self.body,
                                     headers=self.headers)
            self.assertEqual(stale.status_code, 409)
            self.cursor.fetchall.return_value = [self.row]
            self.point["payload"]["text_hash"] = "tampered"
            changed = self.client.post("/api/v1/evidence/passages/search", json=self.body,
                                       headers=self.headers)
            self.assertEqual(changed.status_code, 409)


if __name__ == "__main__":
    unittest.main()
