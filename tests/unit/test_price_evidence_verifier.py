"""An investigation cannot cite conflicting price, PDF, or graph tool results."""

import copy
import unittest
from dataclasses import replace
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID

from apps.api.app.agents.price_evidence import verify_price_finding
from apps.api.app.domain.pricing import PriceAssessment, RULE_ID
from apps.api.app.services.contract_evidence import EXPECTED_SHA256, VerifiedFixture
from apps.api.app.services.graph_manifest import build_graph_manifest
from datasets.generator.check_minio_contract import BUCKET, object_key
from datasets.generator.seed_price_case import database_id


class PriceEvidenceVerifierTests(unittest.TestCase):
    def setUp(self):
        self.id = lambda label: database_id("DEMO-001", label)
        self.tenant = self.id("TENANT")
        self.invoice = self.id("INV-001")
        self.assessment = PriceAssessment(
            rule_id=RULE_ID, supplier_id=str(self.id("SUP-001")),
            contract_line_id=str(self.id("CL-001")),
            invoice_line_id=str(self.id("IL-001")), currency="INR",
            allowed_unit_price=Decimal("105.00"), invoice_unit_price=Decimal("106.00"),
            quantity=Decimal("10"), excess_amount=Decimal("10.00"), is_violation=True,
        )
        self.locator = {
            "tenant_id": str(self.tenant), "contract_id": str(self.id("CON-001")),
            "contract_line_id": str(self.id("CL-001")),
            "document_id": str(self.id("CON-001/document/v1")),
            "document_version": 1, "sha256": EXPECTED_SHA256,
            "bucket": BUCKET, "object_key": object_key(EXPECTED_SHA256),
            "object_version_id": str(UUID(int=1)), "page": 1,
            "price_clause": "2.1", "tolerance_clause": "2.2", "dates_clause": "2.3",
            "max_unit_price": "100.00", "tolerance_pct": "5.00", "currency": "INR",
        }
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            (self.id("SUP-001"), self.tenant, "Aster Supplies",
             self.id("CON-001"), self.id("SUP-001"),
             self.id("PO-001"), self.id("SUP-001"), self.id("CON-001"),
             self.invoice, self.id("SUP-001"), self.id("PO-001"),
             self.id("IL-001"), self.id("PO-001")),
        ]
        manifest = build_graph_manifest(connection, self.tenant, self.id("IL-001"))
        self.chain = {"tenant_id": str(self.tenant), "invoice_id": str(self.invoice),
                      "nodes": manifest["nodes"],
                      "edges": [{**edge, "created_at": "2026-11-06T00:00:00+00:00"}
                                for edge in manifest["edges"]]}
        self.pdf = VerifiedFixture(sha256=EXPECTED_SHA256)

    def verify(self, assessment=None, locator=None, pdf=None, chain=None, tenant=None):
        return verify_price_finding(
            self.tenant if tenant is None else tenant, self.invoice,
            self.assessment if assessment is None else assessment,
            self.locator if locator is None else locator,
            self.pdf if pdf is None else pdf,
            self.chain if chain is None else chain,
        )

    def test_supported_violation_contains_exact_sources_and_decimal_amount(self):
        finding = self.verify()
        self.assertTrue(finding.is_violation)
        self.assertEqual(finding.excess_amount, "10.00")
        self.assertEqual(finding.clauses, ("2.1", "2.2", "2.3"))
        self.assertEqual(finding.document_sha256, EXPECTED_SHA256)
        self.assertEqual(len(finding.graph_edge_ids), 4)

    def test_wrong_tenant_and_missing_graph_cannot_yield_a_finding(self):
        with self.assertRaises(ValueError):
            self.verify(tenant=UUID(int=0))
        with self.assertRaises(ValueError):
            verify_price_finding(self.tenant, self.invoice, self.assessment,
                                 self.locator, self.pdf, None)

    def test_stale_pdf_and_wrong_contract_are_rejected(self):
        with self.assertRaises(ValueError):
            self.verify(pdf=replace(self.pdf, sha256="0" * 64))
        wrong_graph = copy.deepcopy(self.chain)
        next(node for node in wrong_graph["nodes"] if node["label"] == "Contract")["id"] = str(UUID(int=3))
        with self.assertRaises(ValueError):
            self.verify(chain=wrong_graph)
        wrong_edge = copy.deepcopy(self.chain)
        next(edge for edge in wrong_edge["edges"] if edge["type"] == "GOVERNED_BY")["source_id"] = str(UUID(int=4))
        with self.assertRaises(ValueError):
            self.verify(chain=wrong_edge)

    def test_arithmetic_conflict_rejected_and_valid_non_violation_supported(self):
        with self.assertRaises(ValueError):
            self.verify(assessment=replace(self.assessment, excess_amount=Decimal("0")))
        safe = replace(self.assessment, invoice_unit_price=Decimal("105.00"),
                       excess_amount=Decimal("0"), is_violation=False)
        finding = self.verify(assessment=safe)
        self.assertFalse(finding.is_violation)
        self.assertEqual(finding.excess_amount, "0")


if __name__ == "__main__":
    unittest.main()
