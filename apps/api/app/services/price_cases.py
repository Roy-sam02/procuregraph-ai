"""Read one tenant-scoped synthetic price case from PostgreSQL."""

from uuid import UUID

from psycopg import Connection

from apps.api.app.domain.pricing import PriceAssessment, assess_price_case


CASE_QUERY = """
SELECT
    il.id, i.id, i.invoice_number, i.currency, i.invoice_date,
    il.quantity, il.unit_price,
    pol.id, pol.product_id, pol.quantity, pol.unit_price,
    po.id, po.supplier_id, po.contract_id,
    s.id, s.legal_name,
    c.id, c.supplier_id, c.currency, c.start_date, c.end_date,
    p.id, p.sku,
    cl.id, cl.product_id, cl.max_unit_price, cl.tolerance_pct,
    i.supplier_id, i.po_id, pol.po_id
FROM invoice_lines AS il
JOIN invoices AS i ON i.id = il.invoice_id
JOIN po_lines AS pol ON pol.id = il.po_line_id
JOIN purchase_orders AS po ON po.id = i.po_id
JOIN contracts AS c ON c.id = po.contract_id
JOIN suppliers AS s ON s.id = c.supplier_id
JOIN products AS p ON p.id = pol.product_id
LEFT JOIN contract_lines AS cl
    ON cl.contract_id = c.id
   AND cl.product_id = pol.product_id
   AND i.invoice_date BETWEEN cl.effective_from AND cl.effective_to
WHERE il.id = %s AND s.tenant_id = %s
"""


def assess_stored_price_case(
    connection: Connection,
    tenant_id: UUID,
    invoice_line_id: UUID,
) -> PriceAssessment:
    with connection.cursor() as cursor:
        cursor.execute(CASE_QUERY, (invoice_line_id, tenant_id))
        rows = cursor.fetchall()

    if not rows:
        raise LookupError("Invoice line not found for this tenant")
    if len(rows) > 1:
        raise ValueError("Multiple price terms apply to this invoice line")

    (
        line_id, invoice_id, invoice_number, invoice_currency, invoice_date,
        invoice_quantity, invoice_price,
        po_line_id, po_product_id, po_quantity, po_price,
        po_id, po_supplier_id, po_contract_id,
        supplier_id, supplier_name,
        contract_id, contract_supplier_id, contract_currency,
        contract_start, contract_end,
        product_id, product_sku,
        contract_line_id, terms_product_id, max_price, tolerance,
        invoice_supplier_id, invoice_po_id, line_po_id,
    ) = rows[0]

    if contract_line_id is None:
        raise ValueError("No price term applies to this invoice line")
    if not contract_start <= invoice_date <= contract_end:
        raise ValueError("Contract is inactive on the invoice date")
    if (
        invoice_po_id != line_po_id
        or po_id != line_po_id
        or po_contract_id != contract_id
        or supplier_id != contract_supplier_id
        or supplier_id != po_supplier_id
        or supplier_id != invoice_supplier_id
        or product_id != po_product_id
        or product_id != terms_product_id
        or invoice_currency != contract_currency
    ):
        raise ValueError("Stored procurement records disagree")

    case = {
        "supplier": {"id": str(supplier_id), "name": supplier_name},
        "contract_line": {
            "id": str(contract_line_id),
            "contract_id": str(contract_id),
            "supplier_id": str(contract_supplier_id),
            "product_id": str(terms_product_id),
            "currency": contract_currency,
            "max_unit_price": str(max_price),
            "tolerance_pct": str(tolerance),
        },
        "purchase_order": {
            "id": str(po_id),
            "supplier_id": str(po_supplier_id),
            "contract_id": str(po_contract_id),
        },
        "po_line": {
            "id": str(po_line_id),
            "po_id": str(line_po_id),
            "product_id": str(po_product_id),
            "quantity": str(po_quantity),
            "unit_price": str(po_price),
        },
        "invoice": {
            "id": str(invoice_id),
            "supplier_id": str(invoice_supplier_id),
            "po_id": str(invoice_po_id),
            "currency": invoice_currency,
        },
        "invoice_line": {
            "id": str(line_id),
            "invoice_id": str(invoice_id),
            "po_line_id": str(po_line_id),
            "supplier_id": str(invoice_supplier_id),
            "product_id": str(product_id),
            "currency": invoice_currency,
            "quantity": str(invoice_quantity),
            "unit_price": str(invoice_price),
        },
    }
    return assess_price_case(case)
