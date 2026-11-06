import math
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from apps.api.app.ingestion.contract_passages import extract_contract_passages
from apps.api.app.services.contract_evidence import EXPECTED_SHA256
from apps.api.app.services.hash_vectors import DIMENSIONS, MODEL_ID, embed
from apps.api.app.services.qdrant_hash_demo import (
    index_snapshot, point_for, search, validate_snapshot,
)
from datasets.generator.check_minio_contract import BUCKET, object_key
from datasets.generator.export_vector_snapshot import QUERIES, export
from datasets.generator.register_contract_passages import passage_row
from datasets.generator.seed_price_case import database_id


def identifier(label):
    return str(database_id("DEMO-001", label))


@unittest.skipUnless(os.environ.get("PROCUREGRAPH_CONTRACT_PDF"), "Set PROCUREGRAPH_CONTRACT_PDF")
class QdrantHashDemoTests(unittest.TestCase):
    def setUp(self):
        pdf = Path(os.environ["PROCUREGRAPH_CONTRACT_PDF"]).read_bytes()
        locator = {
            "tenant_id": identifier("TENANT"), "contract_id": identifier("CON-001"),
            "contract_line_id": identifier("CL-001"),
            "document_id": identifier("CON-001/document/v1"),
            "document_version": 1, "sha256": EXPECTED_SHA256,
            "bucket": BUCKET, "object_key": object_key(EXPECTED_SHA256),
            "object_version_id": "ebe48aff-094e-497e-b03c-035b79be6742",
            "page": 1, "price_clause": "2.1", "tolerance_clause": "2.2",
            "dates_clause": "2.3", "max_unit_price": "100.00",
            "tolerance_pct": "5.00", "currency": "INR",
        }
        manifest = extract_contract_passages(pdf, locator)
        self.locator = locator
        self.snapshot = {**manifest, "tenant_id": locator["tenant_id"],
                         "vectorizer": MODEL_ID, "queries": []}

    def test_vectors_are_deterministic_and_labeled_queries_rank(self):
        passages = validate_snapshot(self.snapshot)
        self.assertEqual(len(embed("tolerance")), DIMENSIONS)
        self.assertAlmostEqual(math.sqrt(sum(x*x for x in embed("tolerance"))), 1)
        self.assertEqual(embed("tolerance"), embed("tolerance"))
        for query, expected in (
            ("maximum unit price for product", "2.1"),
            ("price tolerance above allowed", "2.2"),
            ("effective period apply", "2.3"),
        ):
            vector = embed(query)
            ranked = sorted(passages, key=lambda p: sum(a*b for a,b in zip(vector, embed(p["text"]))),
                            reverse=True)
            self.assertEqual(ranked[0]["clause"], expected)
        with self.assertRaises(ValueError):
            embed("!!!")

    def test_changed_text_or_provenance_is_rejected(self):
        self.snapshot["passages"][0]["text"] = "fabricated passage"
        with self.assertRaisesRegex(ValueError, "hash differs"):
            validate_snapshot(self.snapshot)

    def test_create_then_repeat_checks_points_without_overwriting(self):
        points = [point_for(p) for p in validate_snapshot(self.snapshot)]
        state = {"exists": False, "points": []}

        def fake_request(endpoint, method, path, body=None):
            if method == "GET":
                return None if not state["exists"] else {"result": {
                    "config": {"params": {"vectors": {"size": DIMENSIONS, "distance": "Cosine"}}}}}
            if method == "PUT" and path.endswith("/points?wait=true"):
                state["points"] = [{"id": p["id"], "payload": p["payload"], "vector": p["vector"]}
                                   for p in body["points"]]
                return {"result": {"status": "completed"}}
            if method == "PUT":
                state["exists"] = True
                return {"result": True}
            if path.endswith("/points/count"):
                return {"result": {"count": len(state["points"])}}
            return {"result": state["points"]}

        with patch("apps.api.app.services.qdrant_hash_demo.request_json", side_effect=fake_request):
            self.assertTrue(index_snapshot(self.snapshot, "http://127.0.0.1:6333"))
            self.assertFalse(index_snapshot(self.snapshot, "http://127.0.0.1:6333"))
            state["points"][0]["payload"]["clause"] = "wrong"
            with self.assertRaisesRegex(ValueError, "point differs"):
                index_snapshot(self.snapshot, "http://127.0.0.1:6333")
        self.assertEqual(len(points), 3)

    def test_search_sends_tenant_filter_and_checks_source_payload(self):
        passage = self.snapshot["passages"][1]
        point = point_for(passage)
        requests = []

        def fake_request(endpoint, method, path, body=None):
            requests.append(body)
            return {"result": {"points": [{"id": point["id"],
                                            "payload": point["payload"], "score": 0.7}]}}

        with patch("apps.api.app.services.qdrant_hash_demo.request_json", side_effect=fake_request):
            hits = search(self.snapshot, "http://127.0.0.1:6333", "tolerance",
                          self.snapshot["tenant_id"], 1)
            self.assertEqual(hits[0]["source_id"], passage["id"])
            self.assertEqual(requests[0]["filter"]["must"][0]["match"]["value"],
                             self.snapshot["tenant_id"])
            with self.assertRaisesRegex(ValueError, "no matching"):
                search(self.snapshot, "http://127.0.0.1:6333", "tolerance", identifier("OTHER"))

    def test_export_refuses_chunks_different_from_verified_manifest(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = tuple(passage_row(p) for p in self.snapshot["passages"])
        by_clause = {p["clause"]: p for p in self.snapshot["passages"]}

        def ranking(connection, tenant, query, top_k):
            clause = dict(QUERIES)[query]
            return [{"source_id": by_clause[clause]["id"], "clause": clause}]

        with tempfile.TemporaryDirectory() as folder:
            manifest_path = Path(folder) / "manifest.json"
            output_path = Path(folder) / "snapshot.json"
            manifest_path.write_text(json.dumps({k: v for k, v in self.snapshot.items()
                                                if k not in ("tenant_id", "vectorizer", "queries")}))
            with (patch.dict(os.environ, {"PROCUREGRAPH_DB_PORT": "5432",
                                       "PROCUREGRAPH_DB_PASSWORD": "secret"}),
                  patch("datasets.generator.export_vector_snapshot.psycopg.connect",
                        return_value=connection),
                  patch("datasets.generator.export_vector_snapshot.read_locator",
                        return_value=self.locator),
                  patch("datasets.generator.export_vector_snapshot.search_passages",
                        side_effect=ranking)):
                snapshot = export(manifest_path, output_path)
                self.assertEqual(len(snapshot["queries"]), 3)
                cursor.fetchall.return_value = []
                with self.assertRaisesRegex(ValueError, "chunks differ"):
                    export(manifest_path, output_path)
                self.assertEqual(json.loads(output_path.read_text()), snapshot)


if __name__ == "__main__":
    unittest.main()
