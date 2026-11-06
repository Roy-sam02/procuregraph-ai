import os
from urllib.parse import urlsplit
from uuid import UUID

import psycopg
from botocore.exceptions import BotoCoreError, ClientError
from fastapi.responses import JSONResponse

from apps.api.app.services.price_cases import assess_stored_price_case
from datasets.generator.export_evidence_locator import read_locator
from datasets.generator.verify_evidence_locator import verify_stored_evidence
from decimal import Decimal

from fastapi import FastAPI
from pydantic import BaseModel, Field

from apps.api.app.domain.pricing import is_price_violation

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
        })

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
