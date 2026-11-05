def validate_record_links(case: dict) -> None:
    supplier = case["supplier"]
    contract_line = case["contract_line"]
    purchase_order = case["purchase_order"]
    po_line = case["po_line"]
    invoice = case["invoice"]
    invoice_line = case["invoice_line"]

    links = (
        ("invoice", invoice_line["invoice_id"], invoice["id"]),
        ("invoice PO", invoice["po_id"], purchase_order["id"]),
        ("invoice PO line", invoice_line["po_line_id"], po_line["id"]),
        ("PO line", po_line["po_id"], purchase_order["id"]),
        ("PO contract", purchase_order["contract_id"], contract_line["contract_id"]),
        ("invoice supplier", invoice["supplier_id"], supplier["id"]),
        ("PO supplier", purchase_order["supplier_id"], supplier["id"]),
        ("PO product", po_line["product_id"], contract_line["product_id"]),
        ("invoice product", invoice_line["product_id"], po_line["product_id"]),
        ("invoice currency", invoice["currency"], invoice_line["currency"]),
    )
    for name, actual, expected in links:
        if actual != expected:
            raise ValueError(f"{name} link mismatch: {actual} != {expected}")
