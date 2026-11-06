"""The bounded workflow abstains and skips later tools on missing evidence."""

import unittest
from dataclasses import replace
from decimal import Decimal
from uuid import UUID

from apps.api.app.agents.investigation_workflow import (
    InvestigationReads, investigate_price_case,
)
from tests.unit import test_price_evidence_verifier as source_tests


class InvestigationWorkflowTests(unittest.TestCase):
    def setUp(self):
        fixture = source_tests.PriceEvidenceVerifierTests()
        fixture.setUp()
        self.fixture = fixture
        self.calls = []

        def price(tenant, line):
            self.calls.append(("price", tenant, line))
            return fixture.assessment, fixture.locator

        def pdf(locator):
            self.calls.append(("pdf", locator["document_id"]))
            return fixture.pdf

        def graph(tenant, invoice):
            self.calls.append(("graph", tenant, invoice))
            return fixture.chain

        self.reads = InvestigationReads(price, pdf, graph)

    def run_case(self, reads=None, line=None):
        f = self.fixture
        return investigate_price_case(
            self.reads if reads is None else reads, f.tenant, f.invoice,
            f.id("IL-001") if line is None else line,
        )

    def test_violation_is_held_for_review_with_verified_sources(self):
        result = self.run_case()
        self.assertEqual(result.status, "needs_review")
        self.assertIsNone(result.error_code)
        self.assertEqual(result.finding.excess_amount, "10.00")
        self.assertEqual([call[0] for call in self.calls], ["price", "pdf", "graph"])

    def test_valid_non_violation_completes_without_review(self):
        f = self.fixture
        safe = replace(f.assessment, invoice_unit_price=Decimal("105.00"),
                       excess_amount=Decimal("0"), is_violation=False)
        reads = replace(self.reads, price=lambda tenant, line: (safe, f.locator))
        result = self.run_case(reads)
        self.assertEqual(result.status, "complete")
        self.assertFalse(result.finding.is_violation)

    def test_price_failure_abstains_before_document_and_graph(self):
        def broken_price(tenant, line):
            raise RuntimeError("private database detail")
        result = self.run_case(replace(self.reads, price=broken_price))
        self.assertEqual((result.status, result.error_code),
                         ("abstained", "PRICE_SOURCE_UNAVAILABLE"))
        self.assertIsNone(result.finding)
        self.assertEqual(self.calls, [])

    def test_document_failure_skips_graph_and_hides_exception(self):
        def broken_pdf(locator):
            raise ValueError("private document detail")
        result = self.run_case(replace(self.reads, pdf=broken_pdf))
        self.assertEqual(result.error_code, "DOCUMENT_UNAVAILABLE")
        self.assertEqual([call[0] for call in self.calls], ["price"])
        self.assertNotIn("private", repr(result))

    def test_missing_graph_and_wrong_invoice_line_abstain(self):
        result = self.run_case(replace(self.reads, graph=lambda tenant, invoice: None))
        self.assertEqual(result.error_code, "EVIDENCE_CONFLICT")
        self.assertIsNone(result.finding)
        result = self.run_case(line=UUID(int=999))
        self.assertEqual(result.error_code, "EVIDENCE_CONFLICT")
        self.assertIsNone(result.finding)


if __name__ == "__main__":
    unittest.main()
