import os
import hmac
from urllib.parse import urlsplit
from uuid import UUID

import psycopg
from botocore.exceptions import BotoCoreError, ClientError
from fastapi.responses import JSONResponse, Response

from apps.api.app.services.price_cases import assess_stored_price_case
from datasets.generator.export_evidence_locator import read_locator
from datasets.generator.verify_evidence_locator import read_verified_pdf, verify_stored_evidence
from decimal import Decimal

from fastapi import FastAPI, Header
from pydantic import BaseModel, Field, StrictInt, field_validator

from apps.api.app.domain.pricing import is_price_violation
from apps.api.app.services.passage_search import search_passages

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


@app.post("/api/v1/evidence/passages/search", response_model=PassageSearchResponse)
def search_verified_passages(
    request: PassageSearchRequest, authorization: str | None = Header(default=None),
):
    """Private local-demo lexical search over stored, source-linked chunks."""
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
        with psycopg.connect(
            host="127.0.0.1", port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
            dbname="procuregraph", user="postgres",
            password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
        ) as connection:
            hits = search_passages(connection, request.tenant_id, request.query, request.top_k)
    except (KeyError, psycopg.Error, OSError):
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
