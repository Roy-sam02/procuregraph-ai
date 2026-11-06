"""Check a durable abstained synthetic run and idempotency in local PostgreSQL."""

import os
from uuid import UUID

import psycopg

from apps.api.app.agents.investigation_records import record_investigation, read_investigation
from apps.api.app.agents.investigation_workflow import InvestigationResult
from datasets.generator.seed_price_case import database_id


def main() -> None:
    tenant = database_id("DEMO-001", "TENANT")
    invoice = database_id("DEMO-001", "INV-001")
    line = database_id("DEMO-001", "IL-001")
    result = InvestigationResult("abstained", None, "EVIDENCE_CONFLICT")
    with psycopg.connect(
        host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
        dbname="procuregraph", user="postgres", password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
    ) as connection:
        args = (connection, tenant, invoice, line, "local-check",
                "demo-investigation-abstention-v1", result)
        first = record_investigation(*args)
        if record_investigation(*args) != first:
            raise AssertionError("Repeat idempotency key created another record")
        saved = read_investigation(connection, tenant, first)
        if (saved is None or saved["status"] != "abstained"
                or saved["error_code"] != "EVIDENCE_CONFLICT"
                or saved["finding"] is not None):
            raise AssertionError("Saved abstention differs")
        if read_investigation(connection, UUID(int=0), first) is not None:
            raise AssertionError("Another tenant read an investigation")
        try:
            record_investigation(connection, tenant, invoice, line, "different-actor",
                                 "demo-investigation-abstention-v1", result)
        except ValueError:
            pass
        else:
            raise AssertionError("Reused key accepted different content")
    print("PASS: abstained run saved and repeated with one stable PostgreSQL ID")
    print("PASS: another tenant saw no run; changed content could not reuse its key")


if __name__ == "__main__":
    main()
