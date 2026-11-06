import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apps.api.app.services.retrieval_benchmark import (
    fixture_sha256, load_fixture, score_queries,
)
from datasets.generator.check_semantic_benchmark import check


FIXTURE = Path("datasets/fixtures/retrieval_benchmark_v1.json")


class SemanticBenchmarkTests(unittest.TestCase):
    def test_fixture_labels_and_metric_denominators(self):
        fixture = load_fixture(FIXTURE)
        self.assertEqual(len(fixture["passages"]), 16)
        self.assertEqual(len(fixture["queries"]), 32)
        sample = [
            {"kind": "lexical", "gold": "B01", "hits": ["B02", "B01"]},
            {"kind": "paraphrase", "gold": "B02", "hits": []},
        ]
        scored = score_queries(sample, "hits")
        self.assertEqual(scored["all"]["recall_at_1"], 0)
        self.assertEqual(scored["all"]["recall_at_5"], 0.5)
        self.assertEqual(scored["all"]["mrr_at_10"], 0.25)

    def test_mismatched_postgres_fixture_is_rejected_before_model(self):
        fixture = load_fixture(FIXTURE)
        with tempfile.TemporaryDirectory() as folder:
            lexical = Path(folder) / "lexical.json"
            lexical.write_text(json.dumps({
                "dataset_id": fixture["dataset_id"], "tenant_id": fixture["tenant_id"],
                "fixture_sha256": "not-the-locked-fixture", "queries": fixture["queries"],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "locked fixture"):
                check(FIXTURE, lexical, Path(folder) / "report.json",
                      "http://127.0.0.1:6333", Path(folder), encoder=object())

    def test_end_to_end_report_uses_same_labeled_sources_and_tenant_filter(self):
        fixture = load_fixture(FIXTURE)
        passage_index = {p["text"]: i for i, p in enumerate(fixture["passages"])}
        gold_index = {q["text"]: next(i for i, p in enumerate(fixture["passages"])
                                        if p["id"] == q["gold"]) for q in fixture["queries"]}

        class FakeEncoder:
            def encode(self, texts):
                vectors = []
                for text in texts:
                    position = passage_index.get(text, gold_index.get(text))
                    vector = [0.0] * 384
                    vector[position] = 1.0
                    vectors.append(vector)
                return vectors

        state = {"created": False, "points": []}

        def fake_request(endpoint, method, path, body=None):
            if method == "GET":
                return None if not state["created"] else {"result": {
                    "config": {"params": {"vectors": {"size": 384, "distance": "Cosine"}}}}}
            if path.endswith("/points/count"):
                return {"result": {"count": len(state["points"])}}
            if method == "PUT" and path.endswith("/points?wait=true"):
                state["points"] = [{**point, "vector": [value * 0.99999
                                  for value in point["vector"]]} for point in body["points"]]
                return {"result": {"status": "completed"}}
            if method == "PUT":
                state["created"] = True
                return {"result": True}
            if path.endswith("/points/query"):
                filters = body["filter"]["must"]
                if filters[1]["match"]["value"] != fixture["tenant_id"]:
                    return {"result": {"points": []}}
                ranked = sorted(state["points"],
                                key=lambda p: sum(a*b for a,b in zip(body["query"], p["vector"])),
                                reverse=True)[:body["limit"]]
                return {"result": {"points": [{"id": p["id"], "payload": p["payload"]}
                                               for p in ranked]}}
            return {"result": state["points"]}

        with tempfile.TemporaryDirectory() as folder:
            lexical = Path(folder) / "lexical.json"
            report_path = Path(folder) / "report.json"
            lexical.write_text(json.dumps({
                "dataset_id": fixture["dataset_id"], "tenant_id": fixture["tenant_id"],
                "fixture_sha256": fixture_sha256(FIXTURE),
                "queries": [{**q, "postgres_ids": [q["gold"]], "postgres_query_ms": 1.0}
                            for q in fixture["queries"]],
            }), encoding="utf-8")
            with patch("datasets.generator.check_semantic_benchmark.request_json",
                       side_effect=fake_request):
                report = check(FIXTURE, lexical, report_path,
                               "http://127.0.0.1:6333", Path(folder), encoder=FakeEncoder())
                self.assertEqual(report["queries"], 32)
                self.assertEqual(report["qdrant_dense"]["metrics"]["all"]["recall_at_1"], 1)
                self.assertEqual(report["postgres_fts"]["metrics"]["all"]["recall_at_5"], 1)
                self.assertEqual(report["failures_at_1"], [])
                self.assertEqual(json.loads(report_path.read_text())["fixture_sha256"], fixture_sha256(FIXTURE))
                self.assertEqual(len(state["points"]), 16)
                self.assertEqual(check(FIXTURE, lexical, report_path,
                                       "http://127.0.0.1:6333", Path(folder), encoder=FakeEncoder())["queries"], 32)


if __name__ == "__main__":
    unittest.main()
