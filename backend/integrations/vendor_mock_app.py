"""FastAPI wrapper for the mock vendor-verification service (OpenAPI docs at /docs).
Run: uvicorn backend.integrations.vendor_mock_app:app --port 8102"""
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.integrations.vendor_mock_core import VendorMock
from scripts.generate_data import build_dataset

app = FastAPI(title="Mock Vendor Verification API", version="1.0",
              description="Checks fictional vendor tax IDs and bank details. Supports outage, timeout and flaky simulation.")
core = VendorMock.from_dataset(build_dataset(42))


class VerifyRequest(BaseModel):
    tax_id: str = Field(min_length=1, max_length=40)
    bank_account: str | None = Field(default=None, max_length=60)
    vendor_code: str | None = Field(default=None, max_length=20)


class SimulateRequest(BaseModel):
    mode: str = Field(pattern="^(normal|down|timeout|flaky|reject_all)$")
    fail_n: int = Field(default=2, ge=0, le=10)


def _respond(method, path, body):
    status, data = core.handle(method, path, {}, body)
    return JSONResponse(data, status_code=status)


@app.get("/health")
def health():
    return _respond("GET", "/health", None)


@app.post("/verify")
def verify(body: VerifyRequest):
    return _respond("POST", "/verify", body.model_dump())


@app.post("/admin/simulate")
def simulate(body: SimulateRequest):
    return _respond("POST", "/admin/simulate", body.model_dump())


@app.post("/admin/reset")
def reset():
    return _respond("POST", "/admin/reset", None)
