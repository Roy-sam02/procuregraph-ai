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