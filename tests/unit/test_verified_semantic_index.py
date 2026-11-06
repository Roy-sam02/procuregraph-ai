import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apps.api.app.ingestion.contract_passages import extract_contract_passages
from apps.api.app.services.contract_evidence import EXPECTED_SHA256
from apps.api.app.services.qdrant_semantic_sources import index_snapshot, search
from datasets.generator.check_minio_contract import BUCKET, object_key
from datasets.generator.check_verified_semantic_index import check
from datasets.generator.seed_price_case import database_id


@unittest.skipUnless(os.environ.get("PROCUREGRAPH_CONTRACT_PDF"), "Set PROCUREGRAPH_CONTRACT_PDF")
class VerifiedSemanticIndexTests(unittest.TestCase):
    def setUp(self):
        locator = {"tenant_id": str(database_id("DEMO-001", "TENANT")),
                   "contract_id": str(database_id("DEMO-001", "CON-001")),
                   "contract_line_id": str(database_id("DEMO-001", "CL-001")),
                   "document_id": str(database_id("DEMO-001", "CON-001/document/v1")),
                   "document_version": 1, "sha256": EXPECTED_SHA256,
                   "bucket": BUCKET, "object_key": object_key(EXPECTED_SHA256),
                   "object_version_id": "ebe48aff-094e-497e-b03c-035b79be6742", "page": 1,
                   "price_clause": "2.1", "tolerance_clause": "2.2", "dates_clause": "2.3",
                   "max_unit_price": "100.00", "tolerance_pct": "5.00", "currency": "INR"}
        manifest = extract_contract_passages(Path(os.environ["PROCUREGRAPH_CONTRACT_PDF"]).read_bytes(), locator)
        self.snapshot = {**manifest, "tenant_id": locator["tenant_id"],
                         "vectorizer": "token-hash-128-v1", "queries": []}

        class FakeEncoder:
            def encode(self, texts):
                vectors = []
                for text in texts:
                    vector = [0.0] * 384
                    vector[0] = 2.0
                    vectors.append(vector)
                return vectors

        self.encoder = FakeEncoder()
        self.state = {"created": False, "points": []}

    def request(self, endpoint, method, path, body=None):
        if method == "GET":
            return None if not self.state["created"] else {"result": {
                "config": {"params": {"vectors": {"size": 384, "distance": "Cosine"}}}}}
        if path.endswith("/points/count"):
            return {"result": {"count": len(self.state["points"])}}
        if method == "PUT" and path.endswith("/points?wait=true"):
            self.state["points"] = body["points"]
            return {"result": {"status": "completed"}}
        if method == "PUT":
            self.state["created"] = True
            return {"result": True}
        if path.endswith("/points/query"):
            self.assertEqual(body["filter"]["must"][3]["match"]["value"], EXPECTED_SHA256)
            if body["filter"]["must"][0]["match"]["value"] != self.snapshot["tenant_id"]:
                return {"result": {"points": []}}
            return {"result": {"points": [
                {"id": point["id"], "payload": point["payload"], "score": 0.9}
                for point in self.state["points"][:body["limit"]]]}}
        return {"result": self.state["points"]}

    def test_index_repeat_and_tenant_filtered_source_search(self):
        with patch("apps.api.app.services.qdrant_semantic_sources.request_json", side_effect=self.request):
            self.assertTrue(index_snapshot(self.snapshot, "http://127.0.0.1:6333", self.encoder))
            self.assertFalse(index_snapshot(self.snapshot, "http://127.0.0.1:6333", self.encoder))
            hits = search(self.snapshot, "http://127.0.0.1:6333", "tolerance",
                          self.snapshot["tenant_id"], self.encoder)
            self.assertEqual(len(hits), 3)
            self.assertEqual({h["source_id"] for h in hits},
                             {p["id"] for p in self.snapshot["passages"]})
            self.assertEqual(search(self.snapshot, "http://127.0.0.1:6333", "tolerance",
                                    str(database_id("OTHER", "TENANT")), self.encoder), [])
            self.state["points"][0]["payload"]["clause"] = "changed"
            with self.assertRaisesRegex(ValueError, "point differs"):
                index_snapshot(self.snapshot, "http://127.0.0.1:6333", self.encoder)

    def test_report_preserves_source_ids_and_separates_diagnostic_from_benchmark(self):
        passages = self.snapshot["passages"]
        self.snapshot["queries"] = [{"query": "price cap", "expected_clause": "2.1",
                                     "postgres_ids": [passages[0]["id"]]}]
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "snapshot.json"
            report = Path(folder) / "report.json"
            source.write_text(json.dumps(self.snapshot), encoding="utf-8")
            with patch("apps.api.app.services.qdrant_semantic_sources.request_json",
                       side_effect=self.request):
                result = check(source, report, "http://127.0.0.1:6333", Path(folder), self.encoder)
            self.assertEqual(result["point_count"], 3)
            self.assertEqual(result["semantic_top1_labeled"], 1)
            self.assertEqual(json.loads(report.read_text())["comparisons"][0]["semantic_source_ids"][0],
                             passages[0]["id"])


if __name__ == "__main__":
    unittest.main()
