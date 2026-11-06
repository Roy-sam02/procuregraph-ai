"""Graph import rejects altered provenance and reconciles existing records."""

import unittest
from unittest.mock import MagicMock, patch
from uuid import NAMESPACE_URL, uuid5

from apps.api.app.services.graph_manifest import build_graph_manifest
from apps.api.app.services.neo4j_price_graph import _write, validate_manifest
from datasets.generator.seed_price_case import database_id


class Neo4jPriceGraphTests(unittest.TestCase):
    def setUp(self):
        tenant = database_id("DEMO-001", "TENANT")
        line = database_id("DEMO-001", "IL-001")
        supplier = database_id("DEMO-001", "SUP-001")
        contract = database_id("DEMO-001", "CON-001")
        order = database_id("DEMO-001", "PO-001")
        invoice = database_id("DEMO-001", "INV-001")
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [
            (supplier, tenant, "Aster Supplies", contract, supplier,
             order, supplier, contract, invoice, supplier, order, line, order)
        ]
        self.manifest = build_graph_manifest(connection, tenant, line)

    def test_checked_manifest_is_accepted(self):
        validate_manifest(self.manifest)

    def test_untrusted_label_tenant_source_and_edge_id_are_rejected(self):
        import copy

        for field, value in (
            ("source_id", str(uuid5(NAMESPACE_URL, "different"))),
            ("tenant_id", str(uuid5(NAMESPACE_URL, "other-tenant"))),
            ("id", str(uuid5(NAMESPACE_URL, "different-edge"))),
        ):
            bad = copy.deepcopy(self.manifest)
            bad["edges"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_manifest(bad)
        bad = copy.deepcopy(self.manifest)
        bad["nodes"][0]["label"] = "InjectedLabel"
        with self.assertRaises(ValueError):
            validate_manifest(bad)

    def test_repeat_import_is_unchanged_and_tampering_fails_before_write(self):
        nodes = {node["id"]: ([node["label"]],
                              {k: v for k, v in node.items() if k != "label"})
                 for node in self.manifest["nodes"]}
        edges = {edge["id"]: {"type": edge["type"], "props": {
            **edge, "created_at": "2026-11-06T12:00:00+00:00"},
            "from_id": edge["from_id"], "to_id": edge["to_id"],
            "from_tenant": edge["tenant_id"], "to_tenant": edge["tenant_id"]}
                 for edge in self.manifest["edges"]}
        tx = MagicMock()
        with patch("apps.api.app.services.neo4j_price_graph._existing",
                   return_value=(nodes, edges)):
            self.assertEqual(_write(tx, self.manifest), {"new_nodes": 0, "new_edges": 0})
            tx.run.assert_not_called()
            edges[self.manifest["edges"][0]["id"]]["props"]["source_id"] = "tampered"
            with self.assertRaisesRegex(ValueError, "edge differs"):
                _write(tx, self.manifest)
            tx.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
