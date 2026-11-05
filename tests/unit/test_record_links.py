import copy
import json
import unittest
from decimal import Decimal
from pathlib import Path

from apps.api.app.domain.pricing import assess_price_case


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "datasets"
    / "fixtures"
    / "price_case_001.json"
)


def load_case():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class RecordLinkTests(unittest.TestCase):
    def test_linked_case_still_produces_expected_assessment(self):
        assessment = assess_price_case(load_case())
        self.assertTrue(assessment.is_violation)
        self.assertEqual(assessment.excess_amount, Decimal("10.00"))

    def test_broken_links_are_rejected_before_arithmetic(self):
        changes = (
            ("invoice_line", "invoice_id", "INV-999", "invoice link mismatch"),
            ("invoice", "po_id", "PO-999", "invoice PO link mismatch"),
            ("invoice_line", "po_line_id", "POL-999", "invoice PO line link mismatch"),
            ("po_line", "po_id", "PO-999", "PO line link mismatch"),
            ("purchase_order", "contract_id", "CON-999", "PO contract link mismatch"),
            ("invoice", "supplier_id", "SUP-999", "invoice supplier link mismatch"),
            ("po_line", "product_id", "PROD-999", "PO product link mismatch"),
        )
        for section, field, value, message in changes:
            with self.subTest(section=section, field=field):
                case = copy.deepcopy(load_case())
                case[section][field] = value
                case["invoice_line"]["unit_price"] = "not-a-number"
                with self.assertRaisesRegex(ValueError, message):
                    assess_price_case(case)
