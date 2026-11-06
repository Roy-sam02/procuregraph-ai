"""Staged live check: PostgreSQL, then MinIO, then Neo4j on a small laptop."""

import argparse
import json
import os
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import psycopg

from apps.api.app.agents.investigation_workflow import (
    InvestigationReads, InvestigationResult, investigate_price_case,
)
from apps.api.app.agents.investigation_records import record_investigation, read_investigation
from apps.api.app.agents.price_evidence import verify_price_finding
from apps.api.app.domain.pricing import PriceAssessment
from apps.api.app.services.contract_evidence import VerifiedFixture
from apps.api.app.services.graph_manifest import build_graph_manifest
from apps.api.app.services.neo4j_graph_api import read_checked_graph
from apps.api.app.services.price_cases import assess_stored_price_case
from datasets.generator.export_evidence_locator import read_locator
from datasets.generator.seed_price_case import database_id
from datasets.generator.verify_evidence_locator import verify_stored_evidence

TENANT = database_id("DEMO-001", "TENANT")
INVOICE = database_id("DEMO-001", "INV-001")
LINE = database_id("DEMO-001", "IL-001")


def save_new(path: Path, content: dict) -> None:
    """A fresh temporary directory prevents reuse of earlier successful checks."""
    with path.open("x", encoding="utf-8") as output:
        json.dump(content, output, sort_keys=True, indent=2, default=str)


def require_current_graph_source(connection) -> None:
    current = build_graph_manifest(connection, TENANT, LINE)
    saved = json.loads(Path(".local-fixtures/price_case_graph_manifest_v1.json")
                       .read_text(encoding="utf-8"))
    if current != saved:
        raise ValueError("Current PostgreSQL links differ from saved graph source")


def price_stage(path: Path) -> None:
    with psycopg.connect(
        host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
        dbname="procuregraph", user="postgres",
        password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
    ) as connection:
        assessment = assess_stored_price_case(connection, TENANT, LINE)
        locator = read_locator(connection, TENANT, UUID(assessment.contract_line_id))
        require_current_graph_source(connection)
    encoded = {key: str(value) if isinstance(value, Decimal) else value
               for key, value in asdict(assessment).items()}
    save_new(path, {"assessment": encoded, "locator": locator})
    print("PASS: current PostgreSQL assessment and graph source captured")


def pdf_stage(price_path: Path, pdf_path: Path) -> None:
    source = json.loads(price_path.read_text(encoding="utf-8"))
    checked = verify_stored_evidence(source["locator"],
                                     os.environ["PROCUREGRAPH_MINIO_ENDPOINT"])
    save_new(pdf_path, asdict(checked))
    print("PASS: exact MinIO object version, PDF hash and clauses checked")


def finish_stage(price_path: Path, pdf_path: Path, result_path: Path | None = None) -> None:
    source = json.loads(price_path.read_text(encoding="utf-8"))
    checked = json.loads(pdf_path.read_text(encoding="utf-8"))
    raw = source["assessment"]
    assessment = PriceAssessment(**{
        key: Decimal(value) if key in {
            "allowed_unit_price", "invoice_unit_price", "quantity", "excess_amount",
        } else value for key, value in raw.items()
    })
    pdf = VerifiedFixture(**checked)
    locator = source["locator"]
    endpoint = os.environ["PROCUREGRAPH_NEO4J_BOLT"]
    password = os.environ["PROCUREGRAPH_NEO4J_PASSWORD"]
    graph_result = []

    def price_read(tenant: UUID, line: UUID):
        if tenant != TENANT or line != LINE:
            raise LookupError("No staged price case for this tenant and line")
        return assessment, locator

    def pdf_read(requested: dict):
        if requested != locator:
            raise ValueError("Staged PDF locator differs")
        return pdf

    def graph_read(tenant: UUID, invoice: UUID):
        chain = read_checked_graph(tenant, invoice, endpoint, password)
        graph_result.append(chain)
        return chain

    reads = InvestigationReads(price_read, pdf_read, graph_read)
    result = investigate_price_case(reads, TENANT, INVOICE, LINE)
    if (result.status != "needs_review" or result.finding is None
            or Decimal(result.finding.excess_amount) != Decimal("10.00")
            or len(result.finding.graph_edge_ids) != 4):
        raise AssertionError(f"Live price investigation did not verify: {result.error_code}")
    print("PASS: staged live investigation held INR 10.00 violation for review with PDF and graph sources")
    wrong_tenant = investigate_price_case(reads, UUID(int=0), INVOICE, LINE)
    if wrong_tenant.status != "abstained" or wrong_tenant.finding is not None:
        raise AssertionError("Other tenant received a price finding")
    print("PASS: another tenant received no investigation finding")
    if result_path is not None:
        save_new(result_path, {"status": result.status,
                               "finding": asdict(result.finding), "chain": graph_result[0]})


def persist_stage(price_path: Path, pdf_path: Path, result_path: Path) -> None:
    """Recheck current PostgreSQL before persisting a staged verified result."""
    initial = json.loads(price_path.read_text(encoding="utf-8"))
    pdf = VerifiedFixture(**json.loads(pdf_path.read_text(encoding="utf-8")))
    report = json.loads(result_path.read_text(encoding="utf-8"))
    if set(report) != {"status", "finding", "chain"} or report["status"] != "needs_review":
        raise ValueError("Staged investigation result differs")
    with psycopg.connect(
        host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
        dbname="procuregraph", user="postgres",
        password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
    ) as connection:
        assessment = assess_stored_price_case(connection, TENANT, LINE)
        locator = read_locator(connection, TENANT, UUID(assessment.contract_line_id))
        require_current_graph_source(connection)
        encoded = {key: str(value) if isinstance(value, Decimal) else value
                   for key, value in asdict(assessment).items()}
        if encoded != initial["assessment"] or locator != initial["locator"]:
            raise ValueError("PostgreSQL source changed during staged investigation")
        finding = verify_price_finding(TENANT, INVOICE, assessment, locator, pdf, report["chain"])
        if json.loads(json.dumps(asdict(finding))) != report["finding"]:
            raise ValueError("Staged finding differs from rechecked sources")
        result = InvestigationResult("needs_review", finding)
        key = "demo-verified-price-investigation-v1"
        args = (connection, TENANT, INVOICE, LINE, "local-check", key, result)
        first = record_investigation(*args)
        if record_investigation(*args) != first:
            raise AssertionError("Repeat created another investigation")
        stored = read_investigation(connection, TENANT, first)
        if (stored is None or stored["status"] != "needs_review"
                or stored["finding"] != report["finding"]):
            raise AssertionError("Persisted finding differs from verified sources")
        if read_investigation(connection, UUID(int=0), first) is not None:
            raise AssertionError("Another tenant read the verified finding")
    print("PASS: verified INR 10.00 finding persisted once with PDF and graph source IDs")
    print("PASS: retry reused its ID; another tenant could not read the finding")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("price", "pdf", "finish", "persist"))
    parser.add_argument("price_file", type=Path)
    parser.add_argument("pdf_file", nargs="?", type=Path)
    parser.add_argument("result_file", nargs="?", type=Path)
    args = parser.parse_args()
    if args.phase == "price":
        price_stage(args.price_file)
    elif args.pdf_file is None:
        parser.error("pdf_file is required for pdf and finish phases")
    elif args.phase == "pdf":
        pdf_stage(args.price_file, args.pdf_file)
    elif args.phase == "finish":
        finish_stage(args.price_file, args.pdf_file, args.result_file)
    elif args.result_file is None:
        parser.error("result_file is required for persist phase")
    else:
        persist_stage(args.price_file, args.pdf_file, args.result_file)


if __name__ == "__main__":
    main()
