import unittest
from decimal import Decimal

from apps.api.app.domain.pricing import is_price_violation


class PriceRuleTests(unittest.TestCase):
    def test_prices_around_limit(self):
        contract = Decimal("100")
        tolerance = Decimal("5")

        self.assertFalse(is_price_violation(contract, tolerance, Decimal("104")))
        self.assertFalse(is_price_violation(contract, tolerance, Decimal("105")))
        self.assertTrue(is_price_violation(contract, tolerance, Decimal("106")))