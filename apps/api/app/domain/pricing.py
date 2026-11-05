from decimal import Decimal


def is_price_violation(
    contract_price: Decimal,
    tolerance_percent: Decimal,
    invoice_price: Decimal,
) -> bool:
    allowed_maximum = contract_price * (
        Decimal("1") + tolerance_percent / Decimal("100")
    )
    return invoice_price > allowed_maximum