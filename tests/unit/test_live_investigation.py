"""Staged sources retain the verified result and reject stale or reused data."""

import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import asdict
from dataclasses import replace
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from datasets.generator.check_live_investigation import (
    finish_stage, pdf_stage, persist_stage, price_stage, save_new,
)
from tests.unit import test_price_evidence_verifier as source_tests


class LiveInvestigationStageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.price = Path(self.temp.name) / "price.json"
        self.pdf = Path(self.temp.name) / "pdf.json"
        self.result = Path(self.temp.name) / "result.json"
        self.fixture = source_tests.PriceEvidenceVerifierTests()
        self.fixture.setUp()
        assessment = asdict(self.fixture.assessment)
        for key in ("allowed_unit_price", "invoice_unit_price", "quantity", "excess_amount"):
            assessment[key] = str(assessment[key])
        save_new(self.price, {"assessment": assessment, "locator": self.fixture.locator})

    def test_pdf_stage_reads_exact_locator_and_writes_checked_hash(self):
        with (patch.dict(os.environ, {"PROCUREGRAPH_MINIO_ENDPOINT": "http://127.0.0.1:9000"}),
              patch("datasets.generator.check_live_investigation.verify_stored_evidence",
                    return_value=self.fixture.pdf) as verify):
            with redirect_stdout(StringIO()):
                pdf_stage(self.price, self.pdf)
        verify.assert_called_once_with(self.fixture.locator, "http://127.0.0.1:9000")
        self.assertEqual(json.loads(self.pdf.read_text())["sha256"], self.fixture.pdf.sha256)

    def test_final_workflow_uses_checked_graph_and_abstains_for_other_tenant(self):
        save_new(self.pdf, asdict(self.fixture.pdf))
        env = {"PROCUREGRAPH_NEO4J_BOLT": "bolt://127.0.0.1:7687",
               "PROCUREGRAPH_NEO4J_PASSWORD": "local-test"}
        with (patch.dict(os.environ, env),
              patch("datasets.generator.check_live_investigation.read_checked_graph",
                    return_value=self.fixture.chain) as graph):
            with redirect_stdout(StringIO()):
                finish_stage(self.price, self.pdf)
        graph.assert_called_once_with(self.fixture.tenant, self.fixture.invoice,
                                      env["PROCUREGRAPH_NEO4J_BOLT"], env["PROCUREGRAPH_NEO4J_PASSWORD"])

    def test_changed_pdf_hash_cannot_pass_final_stage(self):
        save_new(self.pdf, {**asdict(self.fixture.pdf), "sha256": "0" * 64})
        with (patch.dict(os.environ, {"PROCUREGRAPH_NEO4J_BOLT": "bolt://127.0.0.1:7687",
                                  "PROCUREGRAPH_NEO4J_PASSWORD": "local-test"}),
              patch("datasets.generator.check_live_investigation.read_checked_graph",
                    return_value=self.fixture.chain)):
            with self.assertRaisesRegex(AssertionError, "EVIDENCE_CONFLICT"):
                finish_stage(self.price, self.pdf)

    def test_stage_file_cannot_be_reused(self):
        with self.assertRaises(FileExistsError):
            save_new(self.price, {"assessment": "different"})

    def test_changed_current_postgres_graph_source_rejects_price_snapshot(self):
        candidate = Path(self.temp.name) / "second_price.json"
        with (patch.dict(os.environ, {"PROCUREGRAPH_DB_PORT": "5432",
                                  "PROCUREGRAPH_DB_PASSWORD": "local-test"}),
              patch("datasets.generator.check_live_investigation.psycopg.connect"),
              patch("datasets.generator.check_live_investigation.assess_stored_price_case",
                    return_value=self.fixture.assessment),
              patch("datasets.generator.check_live_investigation.read_locator",
                    return_value=self.fixture.locator),
              patch("datasets.generator.check_live_investigation.build_graph_manifest",
                    return_value={"source": "changed"}),
              patch("pathlib.Path.read_text", return_value=json.dumps({"source": "saved"}))):
            with self.assertRaisesRegex(ValueError, "Current PostgreSQL links differ"):
                price_stage(candidate)
        self.assertFalse(candidate.exists())

    def write_verified_result(self):
        save_new(self.pdf, asdict(self.fixture.pdf))
        env = {"PROCUREGRAPH_NEO4J_BOLT": "bolt://127.0.0.1:7687",
               "PROCUREGRAPH_NEO4J_PASSWORD": "local-test"}
        with (patch.dict(os.environ, env),
              patch("datasets.generator.check_live_investigation.read_checked_graph",
                    return_value=self.fixture.chain),
              redirect_stdout(StringIO())):
            finish_stage(self.price, self.pdf, self.result)

    def test_verified_result_is_rechecked_and_stored_once(self):
        self.write_verified_result()
        report = json.loads(self.result.read_text())
        self.assertEqual(report["status"], "needs_review")
        self.assertEqual(report["finding"]["excess_amount"], "10.00")
        saved = {"status": "needs_review", "finding": report["finding"]}
        with (patch.dict(os.environ, {"PROCUREGRAPH_DB_PORT": "5432",
                                  "PROCUREGRAPH_DB_PASSWORD": "local-test"}),
              patch("datasets.generator.check_live_investigation.psycopg.connect"),
              patch("datasets.generator.check_live_investigation.assess_stored_price_case",
                    return_value=self.fixture.assessment),
              patch("datasets.generator.check_live_investigation.read_locator",
                    return_value=self.fixture.locator),
              patch("datasets.generator.check_live_investigation.require_current_graph_source"),
              patch("datasets.generator.check_live_investigation.record_investigation",
                    return_value=UUID(int=5)) as record,
              patch("datasets.generator.check_live_investigation.read_investigation",
                    side_effect=[saved, None]) as read,
              redirect_stdout(StringIO())):
            persist_stage(self.price, self.pdf, self.result)
        self.assertEqual(record.call_count, 2)
        self.assertEqual(read.call_count, 2)

    def test_changed_postgres_price_prevents_persistence(self):
        self.write_verified_result()
        changed = replace(self.fixture.assessment, invoice_unit_price=Decimal("108.00"))
        with (patch.dict(os.environ, {"PROCUREGRAPH_DB_PORT": "5432",
                                  "PROCUREGRAPH_DB_PASSWORD": "local-test"}),
              patch("datasets.generator.check_live_investigation.psycopg.connect"),
              patch("datasets.generator.check_live_investigation.assess_stored_price_case",
                    return_value=changed),
              patch("datasets.generator.check_live_investigation.read_locator",
                    return_value=self.fixture.locator),
              patch("datasets.generator.check_live_investigation.require_current_graph_source"),
              patch("datasets.generator.check_live_investigation.record_investigation") as record):
            with self.assertRaisesRegex(ValueError, "PostgreSQL source changed"):
                persist_stage(self.price, self.pdf, self.result)
        record.assert_not_called()


if __name__ == "__main__":
    unittest.main()
