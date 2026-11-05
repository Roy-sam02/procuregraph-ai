from dataclasses import dataclass
from decimal import Decimal

from apps.api.app.domain.record_links import validate_record_links


RULE_ID = "CONTRACT_UNIT_PRICE_VIOLATION"


@dataclass(frozen=True)
class PriceAssessment:
    rule_id: str
    supplier_id: str
    contract_line_id: str
    invoice_line_id: str
    currency: str
    allowed_unit_price: Decimal
    invoice_unit_price: Decimal
    quantity: Decimal
    excess_amount: Decimal
    is_violation: bool


def allowed_unit_price(
    contract_price: Decimal,
    tolerance_percent: Decimal,
) -> Decimal:
    return contract_price * (
        Decimal("1") + tolerance_percent / Decimal("100")
    )


def is_price_violation(
    contract_price: Decimal,
    tolerance_percent: Decimal,
    invoice_price: Decimal,
) -> bool:
    return invoice_price > allowed_unit_price(
        contract_price, tolerance_percent
    )


def assess_price_case(case: dict) -> PriceAssessment:
    supplier_id = case["supplier"]["id"]
    contract = case["contract_line"]
    invoice = case["invoice_line"]

    if (
        contract["supplier_id"] != supplier_id
        or invoice["supplier_id"] != supplier_id
    ):
        raise ValueError(
            "supplier mismatch between supplier, contract line, and invoice line"
        )
    if contract["product_id"] != invoice["product_id"]:
        raise ValueError(
            "product mismatch between contract line and invoice line"
        )
    if contract["currency"] != invoice["currency"]:
        raise ValueError(
            "currency mismatch between contract line and invoice line"
        )

    validate_record_links(case)

    contract_price = Decimal(contract["max_unit_price"])
    tolerance = Decimal(contract["tolerance_pct"])
    invoice_price = Decimal(invoice["unit_price"])
    quantity = Decimal(invoice["quantity"])
    if quantity <= 0:
        raise ValueError("invoice quantity must be greater than zero")

    allowed = allowed_unit_price(contract_price, tolerance)
    excess = max(Decimal("0"), invoice_price - allowed) * quantity

    return PriceAssessment(
        rule_id=RULE_ID,
        supplier_id=supplier_id,
        contract_line_id=contract["id"],
        invoice_line_id=invoice["id"],
        currency=contract["currency"],
        allowed_unit_price=allowed,
        invoice_unit_price=invoice_price,
        quantity=quantity,
        excess_amount=excess,
        is_violation=is_price_violation(
            contract_price, tolerance, invoice_price
        ),
    )
