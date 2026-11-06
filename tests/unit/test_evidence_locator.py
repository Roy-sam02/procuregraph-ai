import unittest
import os
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from apps.api.app.services.contract_evidence import EXPECTED_SHA256, verify_synthetic_pdf_bytes
from datasets.generator.check_minio_contract import BUCKET, object_key
from datasets.generator.seed_price_case import database_id
from datasets.generator.verify_evidence_locator import validate_locator, verify_stored_evidence


class EvidenceLocatorTests(unittest.TestCase):
    def setUp(self):
        def identifier(label):
            return str(database_id("DEMO-001", label))
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

    def test_wrong_tenant_or_clause_is_rejected(self):
        self.locator["tenant_id"] = str(database_id("OTHER", "TENANT"))
        with self.assertRaisesRegex(ValueError, "disagrees"):
            validate_locator(self.locator)
        self.locator["tenant_id"] = str(database_id("DEMO-001", "TENANT"))
        self.locator["price_clause"] = "2.2"
        with self.assertRaisesRegex(ValueError, "disagrees"):
            validate_locator(self.locator)

    def test_changed_remote_bytes_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            verify_synthetic_pdf_bytes(b"not the contract PDF")

    @unittest.skipUnless(os.environ.get("PROCUREGRAPH_CONTRACT_PDF"), "Set PROCUREGRAPH_CONTRACT_PDF to test the real PDF")
    def test_exact_version_read_and_changed_object_rejected(self):
        pdf = Path(os.environ["PROCUREGRAPH_CONTRACT_PDF"]).read_bytes()

        class FakeS3:
            def __init__(self, body):
                self.body = body
                self.call = None

            def get_object(self, **kwargs):
                self.call = kwargs
                return {"Body": BytesIO(self.body), "ContentType": "application/pdf"}

        good = FakeS3(pdf)
        with patch("datasets.generator.verify_evidence_locator.boto3.client", return_value=good), patch.dict(os.environ, {
            "PROCUREGRAPH_MINIO_USER": "demo-user", "PROCUREGRAPH_MINIO_PASSWORD": "demo-password"
        }):
            verify_stored_evidence(self.locator, "http://127.0.0.1:9000")
        self.assertEqual(good.call, {
            "Bucket": BUCKET, "Key": object_key(EXPECTED_SHA256),
            "VersionId": self.locator["object_version_id"],
        })

        changed = FakeS3(pdf + b"changed")
        with patch("datasets.generator.verify_evidence_locator.boto3.client", return_value=changed), patch.dict(os.environ, {
            "PROCUREGRAPH_MINIO_USER": "demo-user", "PROCUREGRAPH_MINIO_PASSWORD": "demo-password"
        }):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                verify_stored_evidence(self.locator, "http://127.0.0.1:9000")


if __name__ == "__main__":
    unittest.main()
