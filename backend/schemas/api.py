"""Request/response models for the HTTP API (validated by Pydantic, documented in OpenAPI)."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Role = Literal["admin", "reviewer", "ap_clerk", "auditor"]


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginRequest(_Req):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str
    role: Role


class DecisionRequest(_Req):
    decision: Literal["approve", "reject", "request_documents"]
    comment: str | None = Field(default=None, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=80)


class DecisionResponse(BaseModel):
    review_id: int
    invoice_id: int
    decision: str
    invoice_status: str


class PaymentResponse(BaseModel):
    status: Literal["PAID", "PAYMENT_PENDING"]
    payment_id: str | None = None
    replayed: bool = False
    retry: bool = False
    reason: str | None = None


class JobResponse(BaseModel):
    job_id: str
    status: str
    job_type: str | None = None
    progress_pct: int = 0
    attempts: int = 0
    error: str | None = None


class UserCreate(_Req):
    username: str = Field(pattern=r"^[a-z0-9_.-]{3,64}$")
    password: str = Field(min_length=10, max_length=128)
    role: Role

    @field_validator("password")
    @classmethod
    def _strong(cls, v: str) -> str:
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            raise ValueError("password must contain letters and digits")
        return v


class UserUpdate(_Req):
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=128)


class SettingsUpdate(_Req):
    values: dict[str, str] = Field(min_length=1, max_length=20)


class SimulateRequest(_Req):
    mode: Literal["normal", "down", "timeout", "flaky", "reject_all"]
    fail_n: int = Field(default=2, ge=0, le=10)
