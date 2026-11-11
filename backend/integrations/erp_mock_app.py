"""FastAPI wrapper for the mock ERP (OpenAPI docs at /docs).
Run: uvicorn backend.integrations.erp_mock_app:app --port 8101"""
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.integrations.erp_mock_core import ErpMock

app = FastAPI(title="Mock ERP Payment API", version="1.0",
              description="Synthetic payment endpoint. Never connects to a real bank. Requires an Idempotency-Key header.")
core = ErpMock()


class PaymentRequest(BaseModel):
    invoice_number: str = Field(min_length=1, max_length=60)
    vendor_code: str = Field(min_length=1, max_length=20)
    amount: str = Field(pattern=r"^\d+(\.\d{1,2})?$", description="Decimal string, e.g. '1234.50'")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    approval_id: str = Field(min_length=1, description="Id of the recorded human approval")


class SimulateRequest(BaseModel):
    mode: str = Field(pattern="^(normal|down|timeout|flaky)$")
    fail_n: int = Field(default=2, ge=0, le=10)


def _respond(method, path, headers, body):
    status, data = core.handle(method, path, headers, body)
    return JSONResponse(data, status_code=status)


@app.get("/health")
def health():
    return _respond("GET", "/health", {}, None)


@app.post("/payments", status_code=201)
def create_payment(body: PaymentRequest, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    return _respond("POST", "/payments", {"Idempotency-Key": idempotency_key or ""}, body.model_dump())


@app.get("/payments/{payment_id}")
def get_payment(payment_id: str):
    return _respond("GET", f"/payments/{payment_id}", {}, None)


@app.post("/admin/simulate")
def simulate(body: SimulateRequest):
    return _respond("POST", "/admin/simulate", {}, body.model_dump())


@app.post("/admin/reset")
def reset():
    return _respond("POST", "/admin/reset", {}, None)
