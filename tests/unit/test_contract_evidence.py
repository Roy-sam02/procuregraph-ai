"""Actual PDF fixture tests run when its path is supplied."""

import os
import tempfile
import unittest
from pathlib import Path

from apps.api.app.services.contract_evidence import EXPECTED_SHA256, verify_synthetic_pdf


@unittest.skipUnless(os.environ.get("PROCUREGRAPH_CONTRACT_PDF"), "Set PROCUREGRAPH_CONTRACT_PDF to test the real PDF")
class ContractEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.pdf = Path(os.environ["PROCUREGRAPH_CONTRACT_PDF"])

    def test_actual_pdf_and_clauses(self):
        evidence = verify_synthetic_pdf(self.pdf)
        self.assertEqual(evidence.sha256, EXPECTED_SHA256)
        self.assertEqual((evidence.page, evidence.price_clause,
                          evidence.tolerance_clause, evidence.dates_clause),
                         (1, "2.1", "2.2", "2.3"))

    def test_changed_pdf_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            changed = Path(folder) / "changed.pdf"
            changed.write_bytes(self.pdf.read_bytes() + b"\nchanged")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                verify_synthetic_pdf(changed)

    def test_incorrect_clause_reference_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "clause references"):
            verify_synthetic_pdf(self.pdf, clauses=("2.2", "2.1", "2.3"))


if __name__ == "__main__":
    unittest.main()
