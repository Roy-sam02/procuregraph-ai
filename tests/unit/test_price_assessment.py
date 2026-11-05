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


class PriceAssessmentTests(unittest.TestCase):
    def test_valid_fixture_records_price_violation(self):
        assessment = assess_price_case(load_case())

        self.assertEqual(
            assessment.rule_id, "CONTRACT_UNIT_PRICE_VIOLATION"
        )
        self.assertEqual(assessment.supplier_id, "SUP-001")
        self.assertEqual(assessment.contract_line_id, "CL-001")
        self.assertEqual(assessment.invoice_line_id, "IL-001")
        self.assertEqual(assessment.currency, "INR")
        self.assertEqual(
            assessment.allowed_unit_price, Decimal("105.00")
        )
        self.assertEqual(
            assessment.invoice_unit_price, Decimal("106.00")
        )
        self.assertEqual(assessment.quantity, Decimal("10"))
        self.assertEqual(assessment.excess_amount, Decimal("10.00"))
        self.assertTrue(assessment.is_violation)

    def test_rejects_mismatches_before_price_calculation(self):
        changes = (
            ("contract_line", "supplier_id", "SUP-999", "supplier mismatch"),
            ("invoice_line", "supplier_id", "SUP-999", "supplier mismatch"),
            ("invoice_line", "product_id", "PROD-999", "product mismatch"),
            ("invoice_line", "currency", "USD", "currency mismatch"),
        )

        for section, field, value, message in changes:
            with self.subTest(section=section, field=field):
                case = copy.deepcopy(load_case())
                case[section][field] = value
                case["invoice_line"]["unit_price"] = "not-a-number"

                with self.assertRaisesRegex(ValueError, message):
                    assess_price_case(case)

    def test_valid_price_at_limit_has_no_excess(self):
        case = load_case()
        case["invoice_line"]["unit_price"] = "105.00"

        assessment = assess_price_case(case)

        self.assertFalse(assessment.is_violation)
        self.assertEqual(assessment.excess_amount, Decimal("0"))
