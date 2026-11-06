"""The private demo download must authenticate and verify before serving bytes."""

import hashlib
import os
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from apps.api.app.main import app
from apps.api.app.services.contract_evidence import EXPECTED_SHA256
from datasets.generator.check_minio_contract import BUCKET, object_key
from datasets.generator.seed_price_case import database_id


def identifier(label):
    return str(database_id("DEMO-001", label))


class PdfDownloadApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.token = "local-demo-secret-with-at-least-32-characters"
        self.path = (f"/api/v1/pricing/cases/{identifier('IL-001')}/evidence/pdf"
                     f"?tenant_id={identifier('TENANT')}")
        self.environment = {
            "PROCUREGRAPH_ENABLE_DEMO_DB_API": "1",
            "PROCUREGRAPH_DEMO_EVIDENCE_TOKEN": self.token,
            "PROCUREGRAPH_DB_PORT": "5432", "PROCUREGRAPH_DB_PASSWORD": "demo-password",
            "PROCUREGRAPH_MINIO_ENDPOINT": "http://127.0.0.1:9000",
            "PROCUREGRAPH_MINIO_USER": "demo-user", "PROCUREGRAPH_MINIO_PASSWORD": "demo-password",
        }
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

    def test_missing_and_wrong_token_never_read_database_or_object(self):
        with (patch.dict(os.environ, self.environment, clear=True),
              patch("apps.api.app.main.psycopg.connect") as connect,
              patch("apps.api.app.main.read_verified_pdf") as read):
            for headers in ({}, {"Authorization": "Bearer incorrect"}):
                response = self.client.get(self.path, headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")
            connect.assert_not_called()
            read.assert_not_called()

    @unittest.skipUnless(os.environ.get("PROCUREGRAPH_CONTRACT_PDF"), "Set PROCUREGRAPH_CONTRACT_PDF")
    def test_download_returns_only_verified_actual_pdf(self):
        pdf = Path(os.environ["PROCUREGRAPH_CONTRACT_PDF"]).read_bytes()

        class Store:
            data = pdf
            request = None

            def get_object(self, **kwargs):
                self.request = kwargs
                return {"Body": BytesIO(self.data), "ContentType": "application/pdf",
                        "VersionId": kwargs["VersionId"]}

        store = Store()
        assessment = MagicMock(contract_line_id=identifier("CL-001"))
        with (patch.dict(os.environ, self.environment, clear=True),
              patch("apps.api.app.main.psycopg.connect", return_value=MagicMock()),
              patch("apps.api.app.main.assess_stored_price_case", return_value=assessment),
              patch("apps.api.app.main.read_locator", return_value=self.locator),
              patch("datasets.generator.verify_evidence_locator.boto3.client", return_value=store)):
            headers = {"Authorization": f"Bearer {self.token}"}
            response = self.client.get(self.path, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.content, pdf)
            self.assertEqual(response.headers["content-type"], "application/pdf")
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertEqual(response.headers["x-document-sha256"], hashlib.sha256(pdf).hexdigest())
            self.assertEqual(store.request["VersionId"], self.locator["object_version_id"])

            store.data = pdf + b"changed"
            changed = self.client.get(self.path, headers=headers)
            self.assertEqual(changed.status_code, 409)
            self.assertNotIn("application/pdf", changed.headers["content-type"])

    def test_different_tenant_gets_no_pdf(self):
        other = self.path.replace(identifier("TENANT"), str(database_id("OTHER", "TENANT")))
        with (patch.dict(os.environ, self.environment, clear=True),
              patch("apps.api.app.main.psycopg.connect", return_value=MagicMock()),
              patch("apps.api.app.main.assess_stored_price_case", side_effect=LookupError),
              patch("apps.api.app.main.read_verified_pdf") as read):
            response = self.client.get(other, headers={"Authorization": f"Bearer {self.token}"})
            self.assertEqual(response.status_code, 404)
            read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
