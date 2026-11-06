"""A fixed graph read cannot return changed evidence or another tenant's chain."""

import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import MagicMock
from uuid import UUID

from neo4j.exceptions import ServiceUnavailable

from apps.api.app.services.graph_manifest import build_graph_manifest
from apps.api.app.services.neo4j_invoice_query import _read, read_invoice_chain
from datasets.generator.check_neo4j_invoice_query import wait_for_bolt
from datasets.generator.seed_price_case import database_id


class InvoiceGraphQueryTests(unittest.TestCase):
    def setUp(self):
        self.tenant = database_id("DEMO-001", "TENANT")
        self.invoice = database_id("DEMO-001", "INV-001")
        supplier = database_id("DEMO-001", "SUP-001")
        contract = database_id("DEMO-001", "CON-001")
        order = database_id("DEMO-001", "PO-001")
        line = database_id("DEMO-001", "IL-001")
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [
            (supplier, self.tenant, "Aster Supplies", contract, supplier,
             order, supplier, contract, self.invoice, supplier, order, line, order)
        ]
        self.manifest = build_graph_manifest(connection, self.tenant, line)
        nodes = {node["label"]: {key: value for key, value in node.items() if key != "label"}
                 for node in self.manifest["nodes"]}
        edges = {edge["type"]: {**edge, "created_at": "2026-11-06T12:00:00+00:00"}
                 for edge in self.manifest["edges"]}
        self.row = {
            "supplier": nodes["Supplier"], "invoice": nodes["Invoice"],
            "purchase_order": nodes["PurchaseOrder"], "contract": nodes["Contract"],
            "has_invoice": edges["HAS_INVOICE"],
            "references_po": edges["REFERENCES_PO"],
            "governed_by": edges["GOVERNED_BY"],
            "has_contract": edges["HAS_CONTRACT"],
        }
        self.tx = MagicMock()
        self.tx.run.return_value = [self.row]

    def test_bounded_parameterized_read_and_source_provenance(self):
        result = _read(self.tx, self.manifest, str(self.tenant), str(self.invoice))
        query = self.tx.run.call_args.args[0]
        self.assertIn("LIMIT 2", query)
        self.assertIn("$tenant", query)
        self.assertIn("$invoice", query)
        self.assertNotIn(" SET ", query)
        self.assertEqual(self.tx.run.call_args.kwargs,
                         {"tenant": str(self.tenant), "invoice": str(self.invoice)})
        self.assertEqual(len(result["nodes"]), 4)
        self.assertEqual(len(result["edges"]), 4)
        self.assertEqual({edge["source_type"] for edge in result["edges"]},
                         {"contracts", "invoices", "purchase_orders"})

    def test_wrong_tenant_empty_and_expected_chain_missing_fails(self):
        self.tx.run.return_value = []
        self.assertIsNone(_read(self.tx, self.manifest, str(UUID(int=0)), str(self.invoice)))
        with self.assertRaisesRegex(ValueError, "missing"):
            _read(self.tx, self.manifest, str(self.tenant), str(self.invoice))

    def test_tampered_source_or_duplicate_path_is_rejected(self):
        self.row["references_po"]["source_id"] = "tampered"
        with self.assertRaisesRegex(ValueError, "edge differs"):
            _read(self.tx, self.manifest, str(self.tenant), str(self.invoice))
        self.tx.run.return_value = [self.row, self.row]
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            _read(self.tx, self.manifest, str(self.tenant), str(self.invoice))

    def test_public_service_uses_read_transaction(self):
        driver = MagicMock()
        session = driver.session.return_value.__enter__.return_value
        session.execute_read.side_effect = lambda fn, *args: fn(self.tx, *args)
        result = read_invoice_chain(driver, self.manifest, self.tenant, self.invoice)
        self.assertEqual(result["invoice_id"], str(self.invoice))
        session.execute_write.assert_not_called()
        self.assertEqual(driver.session.call_args.kwargs, {"database": "neo4j"})

    def test_slow_start_retries_past_previous_timeout(self):
        driver = MagicMock()
        driver.verify_connectivity.side_effect = [ServiceUnavailable("starting")] * 91 + [None]
        with redirect_stdout(StringIO()) as output:
            wait_for_bolt(driver, pause=lambda seconds: None)
        self.assertEqual(driver.verify_connectivity.call_count, 92)
        self.assertIn("90 checks", output.getvalue())


if __name__ == "__main__":
    unittest.main()
