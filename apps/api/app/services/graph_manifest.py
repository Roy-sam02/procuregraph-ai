"""Read a tenant-scoped price-case relationship projection from PostgreSQL."""

from uuid import UUID, NAMESPACE_URL, uuid5

from psycopg import Connection

GRAPH_QUERY = """
SELECT s.id, s.tenant_id, s.legal_name,
       c.id, c.supplier_id,
       po.id, po.supplier_id, po.contract_id,
       i.id, i.supplier_id, i.po_id,
       il.id, pol.po_id
FROM invoice_lines il
JOIN invoices i ON i.id = il.invoice_id
JOIN purchase_orders po ON po.id = i.po_id
JOIN contracts c ON c.id = po.contract_id
JOIN suppliers s ON s.id = i.supplier_id
JOIN po_lines pol ON pol.id = il.po_line_id
WHERE il.id = %s AND s.tenant_id = %s
"""


def build_graph_manifest(connection: Connection, tenant_id: UUID,
                         invoice_line_id: UUID) -> dict:
    """Keep only checked FK links; no graph database or inferred links involved."""
    with connection.cursor() as cursor:
        cursor.execute(GRAPH_QUERY, (invoice_line_id, tenant_id))
        rows = cursor.fetchall()
    if not rows:
        raise LookupError("Invoice line not found for this tenant")
    if len(rows) != 1:
        raise ValueError("Ambiguous invoice line graph source")
    (supplier, stored_tenant, supplier_name, contract, contract_supplier,
     order, order_supplier, order_contract, invoice, invoice_supplier,
     invoice_order, line, line_order) = rows[0]
    if (stored_tenant != tenant_id or line != invoice_line_id
            or any(value != supplier for value in
                   (contract_supplier, order_supplier, invoice_supplier))
            or order_contract != contract or invoice_order != order
            or line_order != order):
        raise ValueError("Stored procurement links disagree")

    tenant = str(tenant_id)
    nodes = [
        {"label": "Supplier", "id": str(supplier), "tenant_id": tenant,
         "legal_name": supplier_name},
        {"label": "Contract", "id": str(contract), "tenant_id": tenant},
        {"label": "PurchaseOrder", "id": str(order), "tenant_id": tenant},
        {"label": "Invoice", "id": str(invoice), "tenant_id": tenant},
    ]

    def edge(kind: str, source: UUID, target: UUID,
             table: str, record: UUID) -> dict:
        return {
            "id": str(uuid5(NAMESPACE_URL, f"procuregraph/graph/{tenant}/{kind}/{source}/{target}")),
            "type": kind, "from_id": str(source), "to_id": str(target),
            "tenant_id": tenant, "source_type": table, "source_id": str(record),
            "extraction_method": "checked_relational_fk",
        }

    edges = [
        edge("HAS_CONTRACT", supplier, contract, "contracts", contract),
        edge("HAS_INVOICE", supplier, invoice, "invoices", invoice),
        edge("REFERENCES_PO", invoice, order, "invoices", invoice),
        edge("GOVERNED_BY", order, contract, "purchase_orders", order),
    ]
    return {"schema_version": 1, "tenant_id": tenant,
            "invoice_line_id": str(invoice_line_id), "nodes": nodes, "edges": edges}
