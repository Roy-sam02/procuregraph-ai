"""The graph export must preserve tenant and relational source provenance."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

from apps.api.app.services.graph_manifest import build_graph_manifest
from datasets.generator.export_graph_manifest import save_manifest
from datasets.generator.seed_price_case import database_id


class GraphManifestTests(unittest.TestCase):
    def setUp(self):
        self.tenant = database_id("DEMO-001", "TENANT")
        self.line = database_id("DEMO-001", "IL-001")
        self.supplier = database_id("DEMO-001", "SUP-001")
        self.contract = database_id("DEMO-001", "CON-001")
        self.order = database_id("DEMO-001", "PO-001")
        self.invoice = database_id("DEMO-001", "INV-001")
        self.row = (self.supplier, self.tenant, "Aster Supplies",
                    self.contract, self.supplier,
                    self.order, self.supplier, self.contract,
                    self.invoice, self.supplier, self.order,
                    self.line, self.order)
        self.connection = MagicMock()
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.cursor.fetchall.return_value = [self.row]

    def test_checked_source_ids_and_repeatable_manifest(self):
        manifest = build_graph_manifest(self.connection, self.tenant, self.line)
        self.assertEqual(self.cursor.execute.call_args.args[1], (self.line, self.tenant))
        self.assertEqual([node["label"] for node in manifest["nodes"]],
                         ["Supplier", "Contract", "PurchaseOrder", "Invoice"])
        self.assertEqual([edge["type"] for edge in manifest["edges"]],
                         ["HAS_CONTRACT", "HAS_INVOICE", "REFERENCES_PO", "GOVERNED_BY"])
        self.assertEqual([edge["source_id"] for edge in manifest["edges"]],
                         [str(self.contract), str(self.invoice), str(self.invoice), str(self.order)])
        self.assertTrue(all(edge["tenant_id"] == str(self.tenant)
                            and edge["extraction_method"] == "checked_relational_fk"
                            for edge in manifest["edges"]))
        self.assertEqual(manifest, build_graph_manifest(self.connection, self.tenant, self.line))

    def test_wrong_tenant_and_inconsistent_links_fail(self):
        self.cursor.fetchall.return_value = []
        with self.assertRaises(LookupError):
            build_graph_manifest(self.connection, UUID(int=0), self.line)
        self.cursor.fetchall.return_value = [self.row, self.row]
        with self.assertRaises(ValueError):
            build_graph_manifest(self.connection, self.tenant, self.line)
        for index in (1, 4, 6, 7, 9, 10, 11, 12):
            changed = list(self.row)
            changed[index] = UUID(int=0)
            self.cursor.fetchall.return_value = [changed]
            with self.subTest(index=index), self.assertRaises(ValueError):
                build_graph_manifest(self.connection, self.tenant, self.line)

    def test_existing_manifest_is_never_replaced_silently(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "manifest.json"
            manifest = build_graph_manifest(self.connection, self.tenant, self.line)
            self.assertTrue(save_manifest(manifest, path))
            saved = path.read_bytes()
            self.assertFalse(save_manifest(manifest, path))
            self.assertEqual(path.read_bytes(), saved)
            with self.assertRaisesRegex(ValueError, "no file overwritten"):
                save_manifest({**manifest, "edges": []}, path)
            self.assertEqual(path.read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()
