"""Fixed two-hop, tenant-scoped invoice graph query with provenance checks."""

from uuid import UUID

from apps.api.app.services.neo4j_price_graph import _check_existing, validate_manifest

INVOICE_CHAIN_QUERY = """
MATCH (s:Supplier {tenant_id:$tenant})-[hi:HAS_INVOICE {tenant_id:$tenant}]->
      (i:Invoice {tenant_id:$tenant, id:$invoice})
MATCH (i)-[rp:REFERENCES_PO {tenant_id:$tenant}]->
      (po:PurchaseOrder {tenant_id:$tenant})
MATCH (po)-[gb:GOVERNED_BY {tenant_id:$tenant}]->
      (c:Contract {tenant_id:$tenant})
MATCH (s)-[hc:HAS_CONTRACT {tenant_id:$tenant}]->(c)
RETURN properties(s) AS supplier, properties(i) AS invoice,
       properties(po) AS purchase_order, properties(c) AS contract,
       properties(hi) AS has_invoice, properties(rp) AS references_po,
       properties(gb) AS governed_by, properties(hc) AS has_contract
LIMIT 2
"""

NODE_ALIASES = {
    "Supplier": "supplier", "Invoice": "invoice",
    "PurchaseOrder": "purchase_order", "Contract": "contract",
}
EDGE_ALIASES = {
    "HAS_INVOICE": ("has_invoice", "Supplier", "Invoice"),
    "REFERENCES_PO": ("references_po", "Invoice", "PurchaseOrder"),
    "GOVERNED_BY": ("governed_by", "PurchaseOrder", "Contract"),
    "HAS_CONTRACT": ("has_contract", "Supplier", "Contract"),
}


def _read(tx, manifest: dict, tenant: str, invoice: str) -> dict | None:
    rows = list(tx.run(INVOICE_CHAIN_QUERY, tenant=tenant, invoice=invoice))
    if not rows:
        if tenant == manifest["tenant_id"] and invoice == next(
            node["id"] for node in manifest["nodes"] if node["label"] == "Invoice"
        ):
            raise ValueError("Expected invoice graph chain is missing")
        return None
    if len(rows) != 1:
        raise ValueError("Ambiguous invoice graph chain")
    row = rows[0]
    nodes = {row[alias]["id"]: ([label], row[alias])
             for label, alias in NODE_ALIASES.items()}
    edges = {}
    for kind, (alias, start, end) in EDGE_ALIASES.items():
        props = row[alias]
        edges[props["id"]] = {
            "type": kind, "props": props,
            "from_id": row[NODE_ALIASES[start]]["id"],
            "to_id": row[NODE_ALIASES[end]]["id"],
            "from_tenant": row[NODE_ALIASES[start]]["tenant_id"],
            "to_tenant": row[NODE_ALIASES[end]]["tenant_id"],
        }
    if ({node["id"] for node in manifest["nodes"]} != set(nodes)
            or {edge["id"] for edge in manifest["edges"]} != set(edges)):
        raise ValueError("Invoice graph chain differs from saved source IDs")
    _check_existing(manifest, nodes, edges)
    if len(nodes) != 4 or len(edges) != 4:
        raise ValueError("Invoice graph chain has missing or duplicate records")
    return {
        "tenant_id": tenant, "invoice_id": invoice,
        "nodes": [{"label": node["label"], **nodes[node["id"]][1]}
                  for node in manifest["nodes"]],
        "edges": [edges[edge["id"]]["props"] for edge in manifest["edges"]],
    }


def read_invoice_chain(driver, manifest: dict, tenant_id: UUID,
                       invoice_id: UUID) -> dict | None:
    """Read the fixed chain; no caller-controlled Cypher or variable-length paths."""
    validate_manifest(manifest)
    with driver.session(database="neo4j") as session:
        return session.execute_read(_read, manifest, str(tenant_id), str(invoice_id))
