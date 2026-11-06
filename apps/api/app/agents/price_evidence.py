"""Cross-check verified tool outputs before an investigation can cite a price finding."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from apps.api.app.domain.pricing import PriceAssessment, RULE_ID
from apps.api.app.services.contract_evidence import VerifiedFixture
from datasets.generator.verify_evidence_locator import validate_locator


@dataclass(frozen=True)
class VerifiedPriceFinding:
    tenant_id: str
    invoice_id: str
    invoice_line_id: str
    rule_id: str
    currency: str
    allowed_unit_price: str
    invoice_unit_price: str
    quantity: str
    excess_amount: str
    is_violation: bool
    document_id: str
    document_version: int
    document_sha256: str
    page: int
    clauses: tuple[str, str, str]
    graph_edge_ids: tuple[str, ...]


def verify_price_finding(
    tenant_id: UUID, invoice_id: UUID, assessment: PriceAssessment,
    locator: dict, checked_pdf: VerifiedFixture, chain: dict | None,
) -> VerifiedPriceFinding:
    """Accept only mutually consistent SQL, PDF and bounded graph results.

    The caller must obtain the assessment and locator from tenant-scoped PostgreSQL,
    checked_pdf by reading the exact MinIO version, and chain from the manifest-checked
    Neo4j reader. This pure function does not fetch or trust a generated explanation.
    """
    validate_locator(locator)
    tenant, invoice = str(tenant_id), str(invoice_id)
    if (locator["tenant_id"] != tenant
            or locator["contract_line_id"] != assessment.contract_line_id
            or locator["currency"] != assessment.currency
            or assessment.rule_id != RULE_ID
            or not assessment.invoice_line_id):
        raise ValueError("Price assessment and document source disagree")
    if (checked_pdf.sha256 != locator["sha256"]
            or checked_pdf.version != locator["document_version"]
            or checked_pdf.page != locator["page"]
            or (checked_pdf.price_clause, checked_pdf.tolerance_clause,
                checked_pdf.dates_clause) != (
                    locator["price_clause"], locator["tolerance_clause"],
                    locator["dates_clause"])):
        raise ValueError("Document bytes and price source disagree")

    price = Decimal(locator["max_unit_price"])
    tolerance = Decimal(locator["tolerance_pct"])
    allowed = price * (Decimal("1") + tolerance / Decimal("100"))
    if (assessment.quantity <= 0 or assessment.invoice_unit_price < 0
            or assessment.allowed_unit_price != allowed
            or assessment.excess_amount != max(
                Decimal("0"), assessment.invoice_unit_price - allowed
            ) * assessment.quantity
            or assessment.is_violation != (assessment.invoice_unit_price > allowed)):
        raise ValueError("Price finding arithmetic disagrees with stored terms")

    if not isinstance(chain, dict) or chain.get("tenant_id") != tenant or chain.get("invoice_id") != invoice:
        raise ValueError("Invoice graph chain is absent or belongs to another tenant")
    nodes, edges = chain.get("nodes"), chain.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list) or len(nodes) != 4 or len(edges) != 4:
        raise ValueError("Invoice graph chain is incomplete")
    if any(not isinstance(node, dict) for node in nodes) or any(not isinstance(edge, dict) for edge in edges):
        raise ValueError("Invoice graph records are invalid")
    by_label = {node.get("label"): node for node in nodes}
    by_type = {edge.get("type"): edge for edge in edges}
    if (set(by_label) != {"Supplier", "Invoice", "PurchaseOrder", "Contract"}
            or set(by_type) != {"HAS_INVOICE", "REFERENCES_PO", "GOVERNED_BY", "HAS_CONTRACT"}
            or len({node.get("id") for node in nodes}) != 4
            or len({edge.get("id") for edge in edges}) != 4
            or any(node.get("tenant_id") != tenant or not node.get("id") for node in nodes)
            or any(edge.get("tenant_id") != tenant or not edge.get("id")
                   or not edge.get("created_at")
                   or edge.get("extraction_method") != "checked_relational_fk" for edge in edges)
            or by_label["Supplier"]["id"] != assessment.supplier_id
            or by_label["Invoice"]["id"] != invoice
            or by_label["Contract"]["id"] != locator["contract_id"]):
        raise ValueError("Invoice graph identities disagree with price source")
    links = {
        "HAS_INVOICE": ("Supplier", "Invoice", "invoices", "Invoice"),
        "REFERENCES_PO": ("Invoice", "PurchaseOrder", "invoices", "Invoice"),
        "GOVERNED_BY": ("PurchaseOrder", "Contract", "purchase_orders", "PurchaseOrder"),
        "HAS_CONTRACT": ("Supplier", "Contract", "contracts", "Contract"),
    }
    for kind, (start, end, source_table, source_label) in links.items():
        edge = by_type[kind]
        if (edge.get("from_id") != by_label[start]["id"]
                or edge.get("to_id") != by_label[end]["id"]
                or edge.get("source_type") != source_table
                or edge.get("source_id") != by_label[source_label]["id"]):
            raise ValueError("Invoice graph edge provenance disagrees")
    return VerifiedPriceFinding(
        tenant_id=tenant, invoice_id=invoice,
        invoice_line_id=assessment.invoice_line_id, rule_id=assessment.rule_id,
        currency=assessment.currency, allowed_unit_price=str(allowed),
        invoice_unit_price=str(assessment.invoice_unit_price),
        quantity=str(assessment.quantity), excess_amount=str(assessment.excess_amount),
        is_violation=assessment.is_violation,
        document_id=locator["document_id"], document_version=locator["document_version"],
        document_sha256=locator["sha256"], page=locator["page"],
        clauses=(locator["price_clause"], locator["tolerance_clause"], locator["dates_clause"]),
        graph_edge_ids=tuple(edge["id"] for edge in edges),
    )
