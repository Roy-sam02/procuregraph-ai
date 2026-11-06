"""Only consistent workflow outcomes may become durable findings."""

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import UUID

from apps.api.app.agents.investigation_records import record_investigation, read_investigation
from apps.api.app.agents.investigation_workflow import InvestigationResult
from tests.unit import test_price_evidence_verifier as source_tests


class InvestigationRecordTests(unittest.TestCase):
    def setUp(self):
        f = source_tests.PriceEvidenceVerifierTests()
        f.setUp()
        self.f = f
        self.find = f.verify()
        self.result = InvestigationResult("needs_review", self.find)
        self.key = "synthetic-demo-run-0001"
        self.connection = MagicMock()
        self.cursor = self.connection.cursor.return_value.__enter__.return_value

    def record(self, result=None, actor="demo-actor", key=None):
        f = self.f
        return record_investigation(self.connection, f.tenant, f.invoice,
                                    f.id("IL-001"), actor, key or self.key,
                                    result or self.result)

    def test_one_verified_finding_is_inserted_with_document_and_graph_sources(self):
        self.cursor.fetchone.return_value = (UUID(int=5),)
        self.assertEqual(self.record(), UUID(int=5))
        sql_calls = self.cursor.execute.call_args_list
        self.assertEqual(len(sql_calls), 2)
        self.assertIn("ON CONFLICT", sql_calls[0].args[0])
        self.assertIn("INSERT INTO findings", sql_calls[1].args[0])
        self.assertIn(self.find.document_sha256, sql_calls[1].args[1][-1])
        self.assertIn(self.find.graph_edge_ids[0], sql_calls[1].args[1][-1])

    def test_same_key_and_content_reuses_id_but_changed_content_fails(self):
        self.cursor.fetchone.side_effect = [None, (UUID(int=5), "old")]
        with self.assertRaises(ValueError):
            self.record()
        self.cursor.fetchone.side_effect = None
        self.cursor.reset_mock()
        self.cursor.fetchone.return_value = (UUID(int=5),)
        self.record()
        digest = self.cursor.execute.call_args_list[0].args[1][5]
        self.cursor.reset_mock()
        self.cursor.fetchone.side_effect = [None, (UUID(int=5), digest)]
        self.assertEqual(self.record(), UUID(int=5))
        self.assertEqual(self.cursor.execute.call_count, 2)

    def test_abstention_cannot_store_a_finding_or_unrecognized_error(self):
        self.cursor.fetchone.return_value = (UUID(int=6),)
        result = InvestigationResult("abstained", None, "EVIDENCE_CONFLICT")
        self.assertEqual(self.record(result=result), UUID(int=6))
        self.assertEqual(self.cursor.execute.call_count, 1)
        with self.assertRaises(ValueError):
            self.record(result=InvestigationResult("abstained", self.find, "EVIDENCE_CONFLICT"))
        with self.assertRaises(ValueError):
            self.record(result=InvestigationResult("abstained", None, "unknown"))

    def test_mismatched_finding_is_not_recorded(self):
        with self.assertRaises(ValueError):
            self.record(result=InvestigationResult("needs_review", replace(
                self.find, tenant_id=str(UUID(int=0)))))
        with self.assertRaises(ValueError):
            self.record(result=InvestigationResult("complete", self.find))
        self.cursor.execute.assert_not_called()

    def test_read_is_tenant_filtered_and_returns_saved_evidence(self):
        when = datetime(2026, 11, 6, tzinfo=timezone.utc)
        self.cursor.fetchone.return_value = (
            UUID(int=5), self.f.tenant, self.f.invoice, self.f.id("IL-001"),
            "demo-actor", "needs_review", None, when, UUID(int=6),
            {"document_sha256": self.find.document_sha256},
        )
        saved = read_investigation(self.connection, self.f.tenant, UUID(int=5))
        self.assertEqual(saved["finding"]["document_sha256"], self.find.document_sha256)
        self.assertEqual(self.cursor.execute.call_args.args[1], (self.f.tenant, UUID(int=5)))
        self.cursor.fetchone.return_value = None
        self.assertIsNone(read_investigation(self.connection, UUID(int=0), UUID(int=5)))


if __name__ == "__main__":
    unittest.main()
