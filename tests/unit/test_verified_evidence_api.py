"""A citation is issued only after the exact stored PDF has been checked."""

import os
import unittest
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from apps.api.app.domain.pricing import PriceAssessment
from apps.api.app.main import app
from apps.api.app.services.contract_evidence import EXPECTED_SHA256
from datasets.generator.check_minio_contract import BUCKET, object_key
from datasets.generator.seed_price_case import database_id
from datasets.generator.export_evidence_locator import read_locator


def identifier(label):
    return str(database_id("DEMO-001", label))


class VerifiedEvidenceApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.request = {
            "tenant_id": identifier("TENANT"), "invoice_line_id": identifier("IL-001"),
            "include_verified_evidence": True,
        }
        self.assessment = PriceAssessment(
            rule_id="CONTRACT_UNIT_PRICE_VIOLATION", supplier_id=identifier("SUP-001"),
            contract_line_id=identifier("CL-001"), invoice_line_id=identifier("IL-001"),
            currency="INR", allowed_unit_price=Decimal("105.00"),
            invoice_unit_price=Decimal("106.00"), quantity=Decimal("10"),
            excess_amount=Decimal("10.00"), is_violation=True,
        )
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
        self.environment = {
            "PROCUREGRAPH_ENABLE_DEMO_DB_API": "1",
            "PROCUREGRAPH_DB_PORT": "5432",
            "PROCUREGRAPH_DB_PASSWORD": "demo-password",
            "PROCUREGRAPH_MINIO_ENDPOINT": "http://127.0.0.1:9000",
            "PROCUREGRAPH_MINIO_USER": "demo-user",
            "PROCUREGRAPH_MINIO_PASSWORD": "demo-password",
        }

    def call(self, body=None):
        with (patch.dict(os.environ, self.environment, clear=True),
              patch("apps.api.app.main.psycopg.connect", return_value=MagicMock()),
              patch("apps.api.app.main.assess_stored_price_case", return_value=self.assessment),
              patch("apps.api.app.main.read_locator", return_value=self.locator) as read):
            response = self.client.post("/api/v1/pricing/cases/assess", json=body or self.request)
        return response, read

    def test_plain_assessment_does_not_claim_evidence(self):
        with patch("apps.api.app.main.verify_stored_evidence") as verify:
            response, read = self.call({**self.request, "include_verified_evidence": False})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("evidence_reference", response.json())
        verify.assert_not_called()
        read.assert_not_called()

    def test_database_locator_is_scoped_to_requested_tenant_and_price_term(self):
        row = (
            database_id("DEMO-001", "CON-001/document/v1"),
            database_id("DEMO-001", "TENANT"), database_id("DEMO-001", "CON-001"),
            1, EXPECTED_SHA256, "application/pdf", 1, "fixture", None,
            BUCKET, object_key(EXPECTED_SHA256), self.locator["object_version_id"],
            EXPECTED_SHA256, 1, "2.1", "2.2", "2.3",
            database_id("DEMO-001", "CL-001"), Decimal("100.00"), Decimal("5.00"),
            date(2025, 1, 1), date(2025, 12, 31), "INR", database_id("DEMO-001", "TENANT"),
        )
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [row]
        tenant = database_id("DEMO-001", "TENANT")
        line = database_id("DEMO-001", "CL-001")
        self.assertEqual(read_locator(connection, tenant, line), self.locator)
        self.assertEqual(cursor.execute.call_args.args[1], (line, tenant))
        with self.assertRaises(ValueError):
            read_locator(connection, database_id("OTHER", "TENANT"), line)

    def test_missing_or_conflicting_source_does_not_issue_citation(self):
        with patch("apps.api.app.main.verify_stored_evidence", side_effect=ValueError("bad hash")):
            response, _ = self.call()
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("evidence_reference", response.json())
        self.assertEqual(response.json()["error"]["code"], "EVIDENCE_CONFLICT")

        self.environment.pop("PROCUREGRAPH_MINIO_ENDPOINT")
        response, _ = self.call()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("evidence_reference", response.json())

    @unittest.skipUnless(os.environ.get("PROCUREGRAPH_CONTRACT_PDF"), "Set PROCUREGRAPH_CONTRACT_PDF")
    def test_actual_pdf_verified_before_source_reference(self):
        pdf = Path(os.environ["PROCUREGRAPH_CONTRACT_PDF"]).read_bytes()

        class ObjectStore:
            def __init__(self, data):
                self.data = data
                self.request = None

            def get_object(self, **kwargs):
                self.request = kwargs
                return {"Body": BytesIO(self.data), "ContentType": "application/pdf",
                        "VersionId": kwargs["VersionId"]}

        store = ObjectStore(pdf)
        with patch("datasets.generator.verify_evidence_locator.boto3.client", return_value=store):
            response, read = self.call()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["evidence_reference"], {
            key: self.locator[key] for key in (
                "document_id", "document_version", "sha256", "page", "price_clause",
                "tolerance_clause", "dates_clause",
            )
        } | {"download_path": (
            f"/api/v1/pricing/cases/{self.request['invoice_line_id']}/evidence/pdf"
            f"?tenant_id={self.request['tenant_id']}"
        )})
        self.assertEqual(response.json()["excess_amount"], "10.00")
        self.assertEqual(store.request["VersionId"], self.locator["object_version_id"])
        self.assertEqual(read.call_args.args[1:], (
            database_id("DEMO-001", "TENANT"), database_id("DEMO-001", "CL-001")
        ))

        store.data = pdf + b"changed"
        with patch("datasets.generator.verify_evidence_locator.boto3.client", return_value=store):
            response, _ = self.call()
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("evidence_reference", response.json())


if __name__ == "__main__":
    unittest.main()
