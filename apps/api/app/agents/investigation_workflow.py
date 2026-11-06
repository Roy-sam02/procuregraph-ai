"""Bounded, read-only LangGraph workflow for one synthetic invoice line."""

from dataclasses import dataclass
from typing import Callable, Literal, NotRequired, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from apps.api.app.agents.price_evidence import VerifiedPriceFinding, verify_price_finding
from apps.api.app.domain.pricing import PriceAssessment
from apps.api.app.services.contract_evidence import VerifiedFixture


@dataclass(frozen=True)
class InvestigationReads:
    """Trusted callers supply existing tenant-scoped, source-checking read tools."""

    price: Callable[[UUID, UUID], tuple[PriceAssessment, dict]]
    pdf: Callable[[dict], VerifiedFixture]
    graph: Callable[[UUID, UUID], dict | None]


class InvestigationState(TypedDict):
    tenant_id: UUID
    invoice_id: UUID
    invoice_line_id: UUID
    assessment: NotRequired[PriceAssessment]
    locator: NotRequired[dict]
    checked_pdf: NotRequired[VerifiedFixture]
    chain: NotRequired[dict | None]
    finding: NotRequired[VerifiedPriceFinding]
    error_code: NotRequired[str]


@dataclass(frozen=True)
class InvestigationResult:
    status: Literal["complete", "needs_review", "abstained"]
    finding: VerifiedPriceFinding | None
    error_code: str | None = None


def build_investigation_graph(reads: InvestigationReads):
    """Four fixed steps, no LLM, user-defined query, writes, or unbounded loop."""
    def price_read(state: InvestigationState) -> dict:
        try:
            assessment, locator = reads.price(state["tenant_id"], state["invoice_line_id"])
            return {"assessment": assessment, "locator": locator}
        except Exception:
            return {"error_code": "PRICE_SOURCE_UNAVAILABLE"}

    def pdf_check(state: InvestigationState) -> dict:
        try:
            return {"checked_pdf": reads.pdf(state["locator"])}
        except Exception:
            return {"error_code": "DOCUMENT_UNAVAILABLE"}

    def graph_read(state: InvestigationState) -> dict:
        try:
            return {"chain": reads.graph(state["tenant_id"], state["invoice_id"])}
        except Exception:
            return {"error_code": "GRAPH_UNAVAILABLE"}

    def evidence_check(state: InvestigationState) -> dict:
        try:
            finding = verify_price_finding(
                state["tenant_id"], state["invoice_id"], state["assessment"],
                state["locator"], state["checked_pdf"], state["chain"],
            )
            if finding.invoice_line_id != str(state["invoice_line_id"]):
                raise ValueError("Requested invoice line differs from verified price finding")
            return {"finding": finding}
        except Exception:
            return {"error_code": "EVIDENCE_CONFLICT"}

    def next_or_end(next_node: str):
        def route(state: InvestigationState) -> str:
            return "stop" if state.get("error_code") else "continue"
        return route, {"stop": END, "continue": next_node}

    builder = StateGraph(InvestigationState)
    builder.add_node("price_read", price_read)
    builder.add_node("pdf_check", pdf_check)
    builder.add_node("graph_read", graph_read)
    builder.add_node("evidence_check", evidence_check)
    builder.add_edge(START, "price_read")
    for current, following in (("price_read", "pdf_check"),
                               ("pdf_check", "graph_read"),
                               ("graph_read", "evidence_check")):
        route, destinations = next_or_end(following)
        builder.add_conditional_edges(current, route, destinations)
    builder.add_edge("evidence_check", END)
    return builder.compile()


def investigate_price_case(reads: InvestigationReads, tenant_id: UUID,
                           invoice_id: UUID, invoice_line_id: UUID) -> InvestigationResult:
    """A trusted caller passes identities; this function is not authentication."""
    if any(type(value) is not UUID for value in (tenant_id, invoice_id, invoice_line_id)):
        raise ValueError("Investigation IDs must be UUIDs")
    state = build_investigation_graph(reads).invoke(
        {"tenant_id": tenant_id, "invoice_id": invoice_id,
         "invoice_line_id": invoice_line_id},
        {"recursion_limit": 10},
    )
    if state.get("error_code"):
        return InvestigationResult("abstained", None, state["error_code"])
    finding = state["finding"]
    return InvestigationResult(
        "needs_review" if finding.is_violation else "complete", finding,
    )
