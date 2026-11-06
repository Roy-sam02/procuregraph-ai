import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

from apps.api.app.ingestion.contract_passages import extract_contract_passages
from apps.api.app.services.contract_evidence import EXPECTED_SHA256
from apps.api.app.services.passage_search import search_passages
from datasets.generator.check_minio_contract import BUCKET, object_key
from datasets.generator.register_contract_passages import register
from datasets.generator.seed_price_case import database_id


def identifier(label):
    return str(database_id("DEMO-001", label))


class PassageSearchTests(unittest.TestCase):
    def test_query_is_bounded_and_parameterized(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [(
            UUID(identifier("CL-001")), UUID(identifier("CON-001/document/v1")),
            1, 1, "2.2", 400, 600, EXPECTED_SHA256, EXPECTED_SHA256,
            "Clause 2.2 — Price tolerance", 0.8,
        )]
        tenant = UUID(identifier("TENANT"))
        found = search_passages(connection, tenant, "tolerance", top_k=1)
        self.assertEqual(found[0]["clause"], "2.2")
        self.assertEqual(found[0]["retrieval_method"], "postgres_fts")
        self.assertEqual(cursor.execute.call_args.args[1], ("tolerance", tenant, tenant, 1))
        for query, top_k in (("", 1), ("x" * 201, 1), ("tolerance", 0), ("tolerance", 11)):
            with self.assertRaises(ValueError):
                search_passages(connection, tenant, query, top_k)
        self.assertEqual(cursor.execute.call_count, 1)


@unittest.skipUnless(os.environ.get("PROCUREGRAPH_CONTRACT_PDF"), "Set PROCUREGRAPH_CONTRACT_PDF")
class PassageRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.pdf = Path(os.environ["PROCUREGRAPH_CONTRACT_PDF"]).read_bytes()
        self.locator = {
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
        self.manifest = extract_contract_passages(self.pdf, self.locator)
        self.connection = MagicMock()
        self.connection.__enter__.return_value = self.connection
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.cursor.fetchall.return_value = []

    def register_with(self, supplied):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "manifest.json"
            path.write_text(json.dumps(supplied), encoding="utf-8")
            with (patch.dict(os.environ, {"PROCUREGRAPH_DB_PORT": "5432",
                                       "PROCUREGRAPH_DB_PASSWORD": "secret"}),
                  patch("datasets.generator.register_contract_passages.psycopg.connect",
                        return_value=self.connection),
                  patch("datasets.generator.register_contract_passages.read_locator",
                        return_value=self.locator),
                  patch("datasets.generator.register_contract_passages.read_verified_pdf",
                        return_value=(self.pdf, None))):
                return register(path, "http://127.0.0.1:9000")

    def test_inserts_three_exact_rows_and_rejects_changed_manifest(self):
        self.assertEqual(self.register_with(self.manifest), 3)
        calls = self.cursor.execute.call_args_list
        self.assertEqual(len(calls), 4)  # SELECT followed by three inserts
        self.assertEqual([c.args[1][7] for c in calls[1:]], ["2.1", "2.2", "2.3"])
        self.assertEqual(calls[1].args[1][3], UUID(identifier("CON-001/document/v1")))

        self.cursor.reset_mock()
        changed = json.loads(json.dumps(self.manifest))
        changed["passages"][0]["text"] = "fabricated clause"
        with self.assertRaisesRegex(ValueError, "differs from the verified"):
            self.register_with(changed)
        self.cursor.execute.assert_not_called()

    def test_matching_existing_rows_are_unchanged_and_conflict_fails(self):
        from datasets.generator.register_contract_passages import passage_row

        self.cursor.fetchall.return_value = tuple(passage_row(p) for p in self.manifest["passages"])
        self.assertEqual(self.register_with(self.manifest), 0)
        self.assertEqual(self.cursor.execute.call_count, 1)
        self.cursor.reset_mock()
        self.cursor.fetchall.return_value = [(UUID(int=0),)]
        with self.assertRaisesRegex(ValueError, "immutable chunks differ"):
            self.register_with(self.manifest)
        self.assertEqual(self.cursor.execute.call_count, 1)


if __name__ == "__main__":
    unittest.main()
