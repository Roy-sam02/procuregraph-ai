"""Ranking behavior and private API wiring for verified reciprocal rank fusion."""

import os
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.services.passage_rank_fusion import fuse_passage_rankings


def hit(source_id: str, method: str) -> dict:
    return {"source_id": source_id, "document_id": str(uuid4()),
            "document_version": 1, "page": 1, "clause": "2.2",
            "start_offset": 10, "end_offset": 20, "source_sha256": "a" * 64,
            "text_hash": "b" * 64, "snippet": "Verified contract text",
            "retrieval_method": method, "score": 0.8}


class PassageRankFusionTests(unittest.TestCase):
    def setUp(self):
        self.a = hit(str(uuid4()), "postgres_fts")
        self.b = hit(str(uuid4()), "postgres_fts")
        self.c = hit(str(uuid4()), "qdrant_bge_small")

    def test_overlap_is_deduplicated_and_ranked_above_single_hits(self):
        overlapping = {**self.b, "retrieval_method": "qdrant_bge_small", "score": 0.12}
        hits = fuse_passage_rankings([self.a, self.b], [overlapping, self.c], 2)
        self.assertEqual([entry["source_id"] for entry in hits],
                         [self.b["source_id"], self.a["source_id"]])
        self.assertAlmostEqual(hits[0]["score"], 1 / 62 + 1 / 61)
        self.assertEqual(hits[0]["retrieval_method"], "rrf_60")
        self.assertEqual(hits[0]["snippet"], self.b["snippet"])

    def test_conflicting_or_duplicate_source_fails_closed(self):
        bad = {**self.b, "text_hash": "c" * 64}
        bad["source_id"] = self.a["source_id"]
        with self.assertRaises(ValueError):
            fuse_passage_rankings([self.a], [bad], 1)
        with self.assertRaises(ValueError):
            fuse_passage_rankings([self.a, self.a], [], 1)
        with self.assertRaises(ValueError):
            fuse_passage_rankings([self.a] * 11, [], 1)

    def test_empty_rankings_and_limits(self):
        self.assertEqual(fuse_passage_rankings([], [], 5), [])
        self.assertEqual(len(fuse_passage_rankings([self.a], [], 1)), 1)
        for limit in (0, 11, True):
            with self.assertRaises(ValueError):
                fuse_passage_rankings([], [], limit)

    def test_api_requires_token_and_uses_ten_candidates_per_source(self):
        client = TestClient(app)
        token = "local-demo-secret-with-at-least-32-characters"
        tenant_id = str(uuid4())
        body = {"tenant_id": tenant_id, "query": "price tolerance",
                "top_k": 1, "retrieval_method": "rrf_60"}
        settings = {"PROCUREGRAPH_ENABLE_DEMO_DB_API": "1",
                    "PROCUREGRAPH_DEMO_EVIDENCE_TOKEN": token,
                    "PROCUREGRAPH_DB_PORT": "5432",
                    "PROCUREGRAPH_DB_PASSWORD": "secret",
                    "PROCUREGRAPH_QDRANT_ENDPOINT": "http://127.0.0.1:6333"}
        connection = MagicMock()
        connection.__enter__.return_value = connection
        with (patch.dict(os.environ, settings, clear=True),
              patch("apps.api.app.main.LocalEncoder") as encoder,
              patch("apps.api.app.main.psycopg.connect", return_value=connection) as connect,
              patch("apps.api.app.main.search_passages", return_value=[self.a]) as lexical,
              patch("apps.api.app.main.search_semantic_passages",
                    return_value=[{**self.a, "retrieval_method": "qdrant_bge_small"}]) as semantic):
            denied = client.post("/api/v1/evidence/passages/search", json=body)
            self.assertEqual(denied.status_code, 401)
            connect.assert_not_called()
            encoder.assert_not_called()
            result = client.post("/api/v1/evidence/passages/search", json=body,
                                 headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["hits"][0]["source_id"], self.a["source_id"])
            self.assertEqual(lexical.call_args.args[-1], 10)
            self.assertEqual(semantic.call_args.args[3], 10)


if __name__ == "__main__":
    unittest.main()
