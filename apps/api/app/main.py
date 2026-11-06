import hashlib
import hmac
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from urllib.error import URLError
from uuid import UUID
from typing import Literal

import psycopg
from botocore.exceptions import BotoCoreError, ClientError
from fastapi.responses import JSONResponse, Response

from apps.api.app.services.price_cases import assess_stored_price_case
from datasets.generator.export_evidence_locator import read_locator
from datasets.generator.verify_evidence_locator import read_verified_pdf, verify_stored_evidence
from decimal import Decimal

from fastapi import FastAPI, Header, Query
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, field_validator, model_validator

from apps.api.app.domain.pricing import is_price_violation
from apps.api.app.agents.investigation_records import read_investigation, read_review_queue, record_approval
from apps.api.app.services.passage_search import search_passages
from apps.api.app.services.neo4j_graph_api import read_checked_graph
from apps.api.app.services.passage_rank_fusion import CANDIDATE_LIMIT, fuse_passage_rankings
from apps.api.app.services.qdrant_hash_demo import local_endpoint
from apps.api.app.services.semantic_embeddings import LocalEncoder
from apps.api.app.services.semantic_passage_search import search_semantic_passages

app = FastAPI(title="ProcureGraph AI API")


class PriceCheckRequest(BaseModel):
    contract_price: Decimal = Field(gt=0)
    tolerance_percent: Decimal = Field(ge=0, le=100)
    invoice_price: Decimal = Field(ge=0)


class PriceCheckResponse(BaseModel):
    is_violation: bool


@app.get("/health/live")
def health_live():
    return {"status": "ok"}


@app.post("/api/v1/pricing/check", response_model=PriceCheckResponse)
def check_price(request: PriceCheckRequest) -> PriceCheckResponse:
    violation = is_price_violation(
        request.contract_price,
        request.tolerance_percent,
        request.invoice_price,
    )
    return PriceCheckResponse(is_violation=violation)

class StoredPriceRequest(BaseModel):
    tenant_id: UUID
    invoice_line_id: UUID
    include_verified_evidence: bool = False


class EvidenceReference(BaseModel):
    document_id: str
    document_version: int
    sha256: str
    page: int
    price_clause: str
    tolerance_clause: str
    dates_clause: str
    download_path: str


class StoredPriceResponse(BaseModel):
    rule_id: str
    supplier_id: str
    contract_line_id: str
    invoice_line_id: str
    currency: str
    allowed_unit_price: str
    invoice_unit_price: str
    quantity: str
    excess_amount: str
    is_violation: bool
    evidence_reference: EvidenceReference | None = None


def evidence_error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {
        "code": code, "message": message, "request_id": None, "details": None,
    }})


class PassageSearchRequest(BaseModel):
    tenant_id: UUID
    query: str = Field(min_length=1, max_length=200)
    top_k: StrictInt = Field(default=5, ge=1, le=10)
    retrieval_method: Literal["postgres_fts", "qdrant_bge_small", "rrf_60"] = "postgres_fts"

    @field_validator("query")
    @classmethod
    def nonblank_query(cls, query: str) -> str:
        query = query.strip()
        if not query:
            raise ValueError("Query cannot be blank")
        return query


class PassageHit(BaseModel):
    source_id: str
    document_id: str
    document_version: int
    page: int
    clause: str
    start_offset: int
    end_offset: int
    source_sha256: str
    text_hash: str
    snippet: str
    retrieval_method: str
    score: float


class PassageSearchResponse(BaseModel):
    hits: list[PassageHit]


class InvoiceGraphRequest(BaseModel):
    tenant_id: UUID
    invoice_id: UUID


class GraphNode(BaseModel):
    label: Literal["Supplier", "Contract", "PurchaseOrder", "Invoice"]
    id: str
    tenant_id: str
    legal_name: str | None = None


class GraphEdge(BaseModel):
    id: str
    type: Literal["HAS_CONTRACT", "HAS_INVOICE", "REFERENCES_PO", "GOVERNED_BY"]
    from_id: str
    to_id: str
    tenant_id: str
    source_type: str
    source_id: str
    extraction_method: str
    created_at: str


class InvoiceGraph(BaseModel):
    tenant_id: str
    invoice_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class InvoiceGraphResponse(BaseModel):
    chain: InvoiceGraph | None


class StoredFinding(BaseModel):
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
    clauses: list[str] = Field(min_length=3, max_length=3)
    graph_edge_ids: list[str] = Field(min_length=4, max_length=4)


class StoredInvestigation(BaseModel):
    id: str
    tenant_id: str
    invoice_id: str
    invoice_line_id: str
    created_by: str
    status: Literal["complete", "needs_review", "abstained"]
    error_code: str | None
    created_at: str
    finding_id: str | None
    finding: StoredFinding | None

    @model_validator(mode="after")
    def consistent_result(self):
        if (self.status == "abstained") != (self.finding is None):
            raise ValueError("Saved investigation status and finding disagree")
        if (self.status == "abstained") != (self.error_code is not None):
            raise ValueError("Saved investigation status and error disagree")
        if self.finding is not None and (
            self.finding.tenant_id != self.tenant_id
            or self.finding.invoice_id != self.invoice_id
            or self.finding.invoice_line_id != self.invoice_line_id
            or (self.finding_id is None)
            or self.finding.is_violation != (self.status == "needs_review")
        ):
            raise ValueError("Saved finding identity differs from investigation")
        if self.finding is None and self.finding_id is not None:
            raise ValueError("Saved finding ID has no finding")
        return self


class ReviewQueueItem(BaseModel):
    id: str
    invoice_id: str
    invoice_line_id: str
    created_at: str
    finding_id: str
    rule_id: str
    currency: str
    excess_amount: str
    status: Literal["needs_review"]


class ReviewQueueResponse(BaseModel):
    items: list[ReviewQueueItem]


class ReviewerIdentity(BaseModel):
    reviewer_id: UUID
    tenant_id: UUID
    role: Literal["reviewer"] = "reviewer"


class DemoReviewerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer_id: UUID
    tenant_id: UUID
    token_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def authenticated_reviewer(tenant_id: UUID, authorization: str | None):
    """Resolve the reviewer and tenant grant before opening a database connection."""
    config = os.environ.get("PROCUREGRAPH_DEMO_REVIEWER")
    if os.environ.get("PROCUREGRAPH_ENABLE_DEMO_DB_API") != "1" or config is None:
        return evidence_error(404, "NOT_FOUND", "Demo reviewer access is unavailable")
    try:
        reviewer = DemoReviewerConfig.model_validate_json(config)
    except ValidationError:
        return evidence_error(503, "REVIEWER_UNAVAILABLE", "Demo reviewer configuration is invalid")
    shared_token = os.environ.get("PROCUREGRAPH_DEMO_EVIDENCE_TOKEN", "")
    shared_digest = hashlib.sha256(shared_token.encode("utf-8")).hexdigest()
    if hmac.compare_digest(reviewer.token_sha256, shared_digest):
        return evidence_error(503, "REVIEWER_UNAVAILABLE", "Reviewer credentials must be separate")

    scheme, _, token = (authorization or "").partition(" ")
    if (scheme.lower() != "bearer" or re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is None
            or not hmac.compare_digest(
                hashlib.sha256(token.encode("ascii")).hexdigest(), reviewer.token_sha256
            )):
        denied = evidence_error(401, "UNAUTHORIZED", "A reviewer token is required")
        denied.headers["WWW-Authenticate"] = "Bearer"
        return denied
    if tenant_id != reviewer.tenant_id:
        return evidence_error(403, "FORBIDDEN", "Reviewer access is denied for this tenant")
    return ReviewerIdentity(reviewer_id=reviewer.reviewer_id, tenant_id=reviewer.tenant_id)


@app.get("/api/v1/review/me", response_model=ReviewerIdentity)
def get_reviewer_identity(
    tenant_id: UUID, response: Response,
    authorization: str | None = Header(default=None),
):
    identity = authenticated_reviewer(tenant_id, authorization)
    if isinstance(identity, JSONResponse):
        return identity
    response.headers["Cache-Control"] = "no-store"
    return identity


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def nonblank_reason(cls, reason: str) -> str:
        reason = reason.strip()
        if not reason:
            raise ValueError("A decision reason is required")
        return reason


class ApprovalResponse(BaseModel):
    id: UUID
    finding_id: UUID
    actor_id: UUID
    tenant_id: UUID
    decision: Literal["approved", "rejected"]


@app.post("/api/v1/review/findings/{finding_id}/decision", response_model=ApprovalResponse)
def submit_review_decision(
    finding_id: UUID, request: ApprovalRequest, response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=16, max_length=128),
    authorization: str | None = Header(default=None),
):
    identity = authenticated_reviewer(request.tenant_id, authorization)
    if isinstance(identity, JSONResponse):
        return identity
    try:
        with psycopg.connect(
            host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
            dbname="procuregraph", user="postgres",
            password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
        ) as connection:
            approval_id = record_approval(
                connection, identity.tenant_id, finding_id, identity.reviewer_id,
                request.decision, request.reason, idempotency_key,
            )
    except ValueError:
        return evidence_error(409, "DECISION_CONFLICT", "Decision could not be recorded")
    except (KeyError, psycopg.Error):
        return evidence_error(503, "DATABASE_UNAVAILABLE", "Demo database could not be reached")
    response.headers["Cache-Control"] = "no-store"
    return ApprovalResponse(id=approval_id, finding_id=finding_id,
                            actor_id=identity.reviewer_id, tenant_id=identity.tenant_id,
                            decision=request.decision)


@app.get("/api/v1/review/queue", response_model=ReviewQueueResponse)
def get_review_queue(
    tenant_id: UUID, limit: int = Query(default=10, ge=1, le=20),
    authorization: str | None = Header(default=None),
):
    """Private local worklist; a shared demo token is not user authorization."""
    if os.environ.get("PROCUREGRAPH_ENABLE_DEMO_DB_API") != "1":
        return evidence_error(404, "NOT_FOUND", "Demo review queue is unavailable")
    token = os.environ.get("PROCUREGRAPH_DEMO_EVIDENCE_TOKEN", "")
    if len(token) < 32:
        return evidence_error(503, "EVIDENCE_UNAVAILABLE", "Demo access is not configured")
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not authorization or not authorization.startswith("Bearer ") or not hmac.compare_digest(
        supplied, token
    ):
        response = evidence_error(401, "UNAUTHORIZED", "A demo evidence token is required")
        response.headers["WWW-Authenticate"] = "Bearer"
        return response
    try:
        with psycopg.connect(
            host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
            dbname="procuregraph", user="postgres",
            password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
        ) as connection:
            rows = read_review_queue(connection, tenant_id, limit)
        return ReviewQueueResponse.model_validate({"items": rows})
    except ValidationError:
        return evidence_error(409, "EVIDENCE_CONFLICT", "Stored review queue is inconsistent")
    except (KeyError, ValueError, psycopg.Error):
        return evidence_error(503, "DATABASE_UNAVAILABLE", "Demo database could not be reached")


@app.get("/api/v1/investigations/{investigation_id}", response_model=StoredInvestigation)
def get_stored_investigation(
    investigation_id: UUID, tenant_id: UUID,
    authorization: str | None = Header(default=None),
):
    """Private demo record read; the shared token is not tenant-bound identity."""
    if os.environ.get("PROCUREGRAPH_ENABLE_DEMO_DB_API") != "1":
        return evidence_error(404, "NOT_FOUND", "Demo investigation is unavailable")
    token = os.environ.get("PROCUREGRAPH_DEMO_EVIDENCE_TOKEN", "")
    if len(token) < 32:
        return evidence_error(503, "EVIDENCE_UNAVAILABLE", "Demo access is not configured")
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not authorization or not authorization.startswith("Bearer ") or not hmac.compare_digest(
        supplied, token
    ):
        response = evidence_error(401, "UNAUTHORIZED", "A demo evidence token is required")
        response.headers["WWW-Authenticate"] = "Bearer"
        return response
    try:
        with psycopg.connect(
            host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
            dbname="procuregraph", user="postgres",
            password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
        ) as connection:
            saved = read_investigation(connection, tenant_id, investigation_id)
        if saved is None:
            return evidence_error(404, "NOT_FOUND", "Investigation not found")
        return StoredInvestigation.model_validate(saved)
    except ValidationError:
        return evidence_error(409, "EVIDENCE_CONFLICT", "Stored investigation is inconsistent")
    except (KeyError, ValueError, psycopg.Error):
        return evidence_error(503, "DATABASE_UNAVAILABLE", "Demo database could not be reached")


@app.post("/api/v1/graph/invoices/chain", response_model=InvoiceGraphResponse)
def get_invoice_graph(
    request: InvoiceGraphRequest, authorization: str | None = Header(default=None),
):
    """Private synthetic graph read; the token is not production tenant authorization."""
    if os.environ.get("PROCUREGRAPH_ENABLE_DEMO_DB_API") != "1":
        return evidence_error(404, "NOT_FOUND", "Demo invoice graph is unavailable")
    token = os.environ.get("PROCUREGRAPH_DEMO_EVIDENCE_TOKEN", "")
    if len(token) < 32:
        return evidence_error(503, "EVIDENCE_UNAVAILABLE", "Demo graph access is not configured")
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not authorization or not authorization.startswith("Bearer ") or not hmac.compare_digest(
        supplied, token
    ):
        response = evidence_error(401, "UNAUTHORIZED", "A demo evidence token is required")
        response.headers["WWW-Authenticate"] = "Bearer"
        return response
    try:
        chain = read_checked_graph(
            request.tenant_id, request.invoice_id,
            os.environ["PROCUREGRAPH_NEO4J_BOLT"],
            os.environ["PROCUREGRAPH_NEO4J_PASSWORD"],
        )
    except ValueError:
        return evidence_error(409, "EVIDENCE_CONFLICT", "Graph source failed verification")
    except (KeyError, OSError, RuntimeError, FileNotFoundError):
        return evidence_error(503, "GRAPH_UNAVAILABLE", "Demo graph could not be reached")
    return InvoiceGraphResponse(chain=chain)


@app.post("/api/v1/evidence/passages/search", response_model=PassageSearchResponse)
def search_verified_passages(
    request: PassageSearchRequest, authorization: str | None = Header(default=None),
):
    """Private demo search; semantic hits must match current PostgreSQL sources."""
    if os.environ.get("PROCUREGRAPH_ENABLE_DEMO_DB_API") != "1":
        return evidence_error(404, "NOT_FOUND", "Demo passage search is unavailable")
    token = os.environ.get("PROCUREGRAPH_DEMO_EVIDENCE_TOKEN", "")
    if len(token) < 32:
        return evidence_error(503, "EVIDENCE_UNAVAILABLE", "Demo passage access is not configured")
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not authorization or not authorization.startswith("Bearer ") or not hmac.compare_digest(
        supplied, token
    ):
        response = evidence_error(401, "UNAUTHORIZED", "A demo evidence token is required")
        response.headers["WWW-Authenticate"] = "Bearer"
        return response
    try:
        endpoint = None
        encoder = None
        if request.retrieval_method in ("qdrant_bge_small", "rrf_60"):
            try:
                endpoint = local_endpoint(os.environ["PROCUREGRAPH_QDRANT_ENDPOINT"])
            except (KeyError, ValueError) as exc:
                raise OSError("Invalid local Qdrant endpoint") from exc
            encoder = LocalEncoder(Path(".local-fixtures/fastembed_cache"))
        with psycopg.connect(
            host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
            dbname="procuregraph", user="postgres",
            password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
        ) as connection:
            if request.retrieval_method == "postgres_fts":
                hits = search_passages(connection, request.tenant_id, request.query, request.top_k)
            elif request.retrieval_method == "qdrant_bge_small":
                hits = search_semantic_passages(
                    connection, request.tenant_id, request.query, request.top_k,
                    endpoint, encoder,
                )
            else:
                lexical = search_passages(
                    connection, request.tenant_id, request.query, CANDIDATE_LIMIT,
                )
                semantic = search_semantic_passages(
                    connection, request.tenant_id, request.query, CANDIDATE_LIMIT,
                    endpoint, encoder,
                )
                hits = fuse_passage_rankings(lexical, semantic, request.top_k)
    except ValueError:
        return evidence_error(409, "EVIDENCE_CONFLICT", "Semantic source failed verification")
    except (KeyError, psycopg.Error, OSError, URLError, RuntimeError):
        return evidence_error(503, "DATABASE_UNAVAILABLE", "Demo database could not be reached")
    return PassageSearchResponse(hits=hits)


def local_minio_endpoint() -> str:
    endpoint = os.environ["PROCUREGRAPH_MINIO_ENDPOINT"]
    try:
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                or parsed.port is None or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment):
            raise ValueError("Invalid MinIO origin")
    except ValueError as exc:
        raise OSError("Demo MinIO endpoint must be a loopback HTTP origin") from exc
    return endpoint


@app.post(
    "/api/v1/pricing/cases/assess",
    response_model=StoredPriceResponse,
    response_model_exclude_none=True,
)
def assess_stored_case(request: StoredPriceRequest):
    if os.environ.get("PROCUREGRAPH_ENABLE_DEMO_DB_API") != "1":
        return JSONResponse(
            status_code=404,
            content={"error": {
                "code": "NOT_FOUND",
                "message": "Demo case assessment is unavailable",
                "request_id": None,
                "details": None,
            }},
        )

    try:
        with psycopg.connect(
            host="127.0.0.1",
            port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
            dbname="procuregraph",
            user="postgres",
            password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
        ) as connection:
            result = assess_stored_price_case(
                connection, request.tenant_id, request.invoice_line_id
            )
            locator = None
            if request.include_verified_evidence:
                locator = read_locator(
                    connection, request.tenant_id, UUID(result.contract_line_id)
                )
    except KeyError:
        return evidence_error(503, "DATABASE_UNAVAILABLE", "Demo database is not configured")
    except psycopg.OperationalError:
        return evidence_error(503, "DATABASE_UNAVAILABLE", "Demo database could not be reached")
    except LookupError:
        return JSONResponse(
            status_code=404,
            content={"error": {
                "code": "CASE_NOT_FOUND",
                "message": "Invoice line not found for this tenant",
                "request_id": None,
                "details": None,
            }},
        )
    except ValueError:
        return JSONResponse(
            status_code=409,
            content={"error": {
                "code": "CASE_CONFLICT",
                "message": "Stored procurement records need review",
                "request_id": None,
                "details": None,
            }},
        )

    evidence = None
    if locator is not None:
        try:
            endpoint = local_minio_endpoint()
            verify_stored_evidence(locator, endpoint)
        except (KeyError, BotoCoreError, ClientError, OSError):
            return evidence_error(503, "EVIDENCE_UNAVAILABLE", "Stored source could not be checked")
        except ValueError:
            return evidence_error(409, "EVIDENCE_CONFLICT", "Stored source failed verification")
        evidence = EvidenceReference(**{
            name: locator[name] for name in EvidenceReference.model_fields
            if name != "download_path"
        }, download_path=(
            f"/api/v1/pricing/cases/{request.invoice_line_id}/evidence/pdf"
            f"?tenant_id={request.tenant_id}"
        ))

    return StoredPriceResponse(
        rule_id=result.rule_id,
        supplier_id=result.supplier_id,
        contract_line_id=result.contract_line_id,
        invoice_line_id=result.invoice_line_id,
        currency=result.currency,
        allowed_unit_price=str(result.allowed_unit_price),
        invoice_unit_price=str(result.invoice_unit_price),
        quantity=str(result.quantity),
        excess_amount=str(result.excess_amount),
        is_violation=result.is_violation,
        evidence_reference=evidence,
    )


@app.get("/api/v1/pricing/cases/{invoice_line_id}/evidence/pdf")
def download_verified_price_pdf(
    invoice_line_id: UUID, tenant_id: UUID, authorization: str | None = Header(default=None),
):
    """Private local-demo PDF read; every request rechecks PostgreSQL and MinIO."""
    if os.environ.get("PROCUREGRAPH_ENABLE_DEMO_DB_API") != "1":
        return evidence_error(404, "NOT_FOUND", "Demo evidence is unavailable")
    token = os.environ.get("PROCUREGRAPH_DEMO_EVIDENCE_TOKEN", "")
    if len(token) < 32:
        return evidence_error(503, "EVIDENCE_UNAVAILABLE", "Demo evidence access is not configured")
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not authorization or not authorization.startswith("Bearer ") or not hmac.compare_digest(
        supplied, token
    ):
        response = evidence_error(401, "UNAUTHORIZED", "A demo evidence token is required")
        response.headers["WWW-Authenticate"] = "Bearer"
        return response

    try:
        with psycopg.connect(
            host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
            dbname="procuregraph", user="postgres",
            password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
        ) as connection:
            result = assess_stored_price_case(connection, tenant_id, invoice_line_id)
            locator = read_locator(connection, tenant_id, UUID(result.contract_line_id))
    except KeyError:
        return evidence_error(503, "DATABASE_UNAVAILABLE", "Demo database is not configured")
    except psycopg.OperationalError:
        return evidence_error(503, "DATABASE_UNAVAILABLE", "Demo database could not be reached")
    except LookupError:
        return evidence_error(404, "CASE_NOT_FOUND", "Invoice line not found for this tenant")
    except ValueError:
        return evidence_error(409, "EVIDENCE_CONFLICT", "Stored source cannot be linked to this case")

    try:
        data, checked = read_verified_pdf(locator, local_minio_endpoint())
    except (KeyError, BotoCoreError, ClientError, OSError):
        return evidence_error(503, "EVIDENCE_UNAVAILABLE", "Stored source could not be checked")
    except ValueError:
        return evidence_error(409, "EVIDENCE_CONFLICT", "Stored source failed verification")
    return Response(
        content=data, media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="synthetic_contract_CON-001_v1.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Document-SHA256": checked.sha256,
        },
    )
