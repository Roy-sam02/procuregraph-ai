import json
import unittest
from decimal import Decimal
from pathlib import Path

from apps.api.app.domain.pricing import is_price_violation


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "datasets"
    / "fixtures"
    / "price_case_001.json"
)


class PriceFixtureTests(unittest.TestCase):
    def test_invoice_matches_contract_and_exceeds_limit(self):
        case = json.loads(FIXTURE.read_text(encoding="utf-8"))
        supplier = case["supplier"]
        contract = case["contract_line"]
        invoice = case["invoice_line"]

        self.assertEqual(contract["supplier_id"], supplier["id"])
        self.assertEqual(invoice["supplier_id"], supplier["id"])
        self.assertEqual(invoice["product_id"], contract["product_id"])
        self.assertEqual(invoice["currency"], contract["currency"])

        contract_price = Decimal(contract["max_unit_price"])
        tolerance = Decimal(contract["tolerance_pct"])
        invoice_price = Decimal(invoice["unit_price"])
        quantity = Decimal(invoice["quantity"])

        allowed = contract_price * (Decimal("1") + tolerance / Decimal("100"))
        excess = (invoice_price - allowed) * quantity

        self.assertEqual(allowed, Decimal("105.00"))
        self.assertEqual(excess, Decimal("10.00"))
        self.assertTrue(is_price_violation(contract_price, tolerance, invoice_price))