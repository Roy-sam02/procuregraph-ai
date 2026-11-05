"""Focused PostgreSQL checks for the stored synthetic price case."""

import os
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import psycopg

from apps.api.app.services.price_cases import assess_stored_price_case
from datasets.generator.seed_price_case import database_id, load_case, seed_and_verify


def main() -> None:
    fixture = Path("datasets/fixtures/price_case_001.json")
    case = load_case(fixture)
    seed_and_verify(case)

    tenant_id = database_id(case["tenant_id"], "TENANT")
    line_id = database_id(case["tenant_id"], case["invoice_line"]["id"])

    from fastapi.testclient import TestClient
    from unittest.mock import patch

    from apps.api.app.main import app

    client = TestClient(app)
    with patch.dict(os.environ, {"PROCUREGRAPH_ENABLE_DEMO_DB_API": "1"}):
        response = client.post(
            "/api/v1/pricing/cases/assess",
            json={"tenant_id": str(tenant_id), "invoice_line_id": str(line_id)},
        )
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        assert Decimal(response.json()["allowed_unit_price"]) == Decimal("105.00"), response.text
        assert Decimal(response.json()["excess_amount"]) == Decimal("10.00"), response.text
        assert response.json()["is_violation"] is True, response.text

        missing = client.post(
            "/api/v1/pricing/cases/assess",
            json={"tenant_id": str(UUID(int=0)), "invoice_line_id": str(line_id)},
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "CASE_NOT_FOUND"

    print("PASS: demo API assessed stored case and rejected another tenant")
    with psycopg.connect(
        host="127.0.0.1",
        port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
        dbname="procuregraph",
        user="postgres",
        password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
    ) as connection:
        result = assess_stored_price_case(connection, tenant_id, line_id)
        assert result.allowed_unit_price == Decimal("105.00")
        assert result.excess_amount == Decimal("10.00")
        assert result.is_violation
        print("PASS: stored case has INR 105.00 limit and INR 10.00 excess")

        try:
            assess_stored_price_case(connection, UUID(int=0), line_id)
        except LookupError:
            print("PASS: a different tenant cannot retrieve this invoice line")
        else:
            raise AssertionError("Expected tenant lookup to fail")

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE invoice_lines SET unit_price = 108.00 WHERE id = %s",
                (line_id,),
            )
        changed = assess_stored_price_case(connection, tenant_id, line_id)
        assert changed.excess_amount == Decimal("30.00")
        print("PASS: changing the stored price changes the excess to INR 30.00")

        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO contract_lines
                   (id, contract_id, product_id, effective_from, effective_to,
                    max_unit_price, tolerance_pct)
                   SELECT %s, contract_id, product_id, effective_from, effective_to,
                          120.00, tolerance_pct
                   FROM contract_lines WHERE id = %s""",
                (
                    UUID("00000000-0000-0000-0000-000000000999"),
                    database_id(case["tenant_id"], case["contract_line"]["id"]),
                ),
            )
        try:
            assess_stored_price_case(connection, tenant_id, line_id)
        except ValueError as error:
            assert str(error) == "Multiple price terms apply to this invoice line"
            print("PASS: overlapping price terms are rejected")
        else:
            raise AssertionError("Expected overlapping terms to be rejected")


if __name__ == "__main__":
    main()
