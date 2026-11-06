import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apps.api.app.ingestion.contract_passages import (
    extract_contract_passages, normalized_page_text,
)
from apps.api.app.services.contract_evidence import EXPECTED_SHA256
from datasets.generator.build_contract_passages import build
from datasets.generator.check_minio_contract import BUCKET, object_key
from datasets.generator.seed_price_case import database_id


def identifier(label):
    return str(database_id("DEMO-001", label))


@unittest.skipUnless(os.environ.get("PROCUREGRAPH_CONTRACT_PDF"), "Set PROCUREGRAPH_CONTRACT_PDF")
class ContractPassageTests(unittest.TestCase):
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

    def test_three_passages_have_reconstructible_offsets_and_stable_ids(self):
        first = extract_contract_passages(self.pdf, self.locator)
        second = extract_contract_passages(self.pdf, self.locator)
        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], 1)
        self.assertEqual(len(first["passages"]), 3)
        page = normalized_page_text(self.pdf)
        self.assertEqual([p["clause"] for p in first["passages"]], ["2.1", "2.2", "2.3"])
        self.assertEqual(len({p["id"] for p in first["passages"]}), 3)
        for passage in first["passages"]:
            self.assertEqual(page[passage["start_offset"]:passage["end_offset"]], passage["text"])
            self.assertEqual(passage["page_text_hash"], hashlib.sha256(page.encode()).hexdigest())
            self.assertEqual(passage["text_hash"], hashlib.sha256(passage["text"].encode()).hexdigest())
            self.assertEqual(passage["source_sha256"], EXPECTED_SHA256)
            self.assertTrue(passage["text"].startswith(f"Clause {passage['clause']}"))
            self.assertNotIn("Created solely as synthetic evidence", passage["text"])

    def test_changed_bytes_or_clause_reference_fail_before_chunks(self):
        with self.assertRaises(ValueError):
            extract_contract_passages(self.pdf + b"changed", self.locator)
        self.locator["price_clause"] = "2.2"
        with self.assertRaises(ValueError):
            extract_contract_passages(self.pdf, self.locator)

    def test_existing_manifest_is_idempotent_and_conflicts_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / "locator.json", Path(folder) / "passages.json"
            source.write_text(json.dumps(self.locator), encoding="utf-8")
            with patch("datasets.generator.build_contract_passages.read_verified_pdf", return_value=(self.pdf, None)):
                original = build(source, target, "http://127.0.0.1:9000")
                self.assertEqual(build(source, target, "http://127.0.0.1:9000"), original)
                target.write_text('{}', encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "differs"):
                    build(source, target, "http://127.0.0.1:9000")
                self.assertEqual(target.read_text(encoding="utf-8"), '{}')


if __name__ == "__main__":
    unittest.main()
