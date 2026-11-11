"""Pydantic schemas that every extraction result must satisfy before it is stored.
Missing business fields are allowed here (they become VAL_MISSING_FIELD exceptions later);
this layer only guarantees types, ranges and shape."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

__all__ = ["ExtractedInvoice", "ExtractedPO", "ExtractedGRN", "ExtractedVendor", "validate_structured", "ValidationError"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def _no_floats(cls, v):
        if isinstance(v, float):
            raise ValueError("floats are not allowed for financial values")
        return v


class ExtractedLine(_Strict):
    line_no: int = Field(ge=1, le=999)
    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(ge=0, le=Decimal("1000000"))
    unit_price: Decimal = Field(ge=0, le=Decimal("100000000"))
    discount_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    line_total: Decimal
    tax_amount: Decimal


class ExtractedInvoice(_Strict):
    invoice_number: str | None = Field(default=None, max_length=60)
    vendor_name_raw: str | None = Field(default=None, max_length=200)
    vendor_tax_id_raw: str | None = Field(default=None, max_length=40)
    bank_account_raw: str | None = Field(default=None, max_length=60)
    invoice_date: date | None = None
    due_date: date | None = None
    po_number: str | None = Field(default=None, max_length=30)
    grn_number: str | None = Field(default=None, max_length=30)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    subtotal: Decimal | None = None
    tax_total: Decimal | None = None
    grand_total: Decimal | None = None
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[ExtractedLine] = Field(default_factory=list, max_length=200)


class _POLine(_Strict):
    line_no: int = Field(ge=1)
    description: str = Field(min_length=1, max_length=300)
    quantity: Decimal = Field(ge=0)
    unit_price: Decimal = Field(ge=0)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)


class ExtractedPO(_Strict):
    po_number: str = Field(min_length=1, max_length=30)
    vendor_code: str = Field(min_length=1, max_length=20)
    order_date: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    lines: list[_POLine] = Field(min_length=1, max_length=200)


class _GRNLine(_Strict):
    po_line_no: int = Field(ge=1)
    description: str = Field(min_length=1, max_length=300)
    quantity_received: Decimal = Field(ge=0)


class ExtractedGRN(_Strict):
    grn_number: str = Field(min_length=1, max_length=30)
    po_number: str = Field(min_length=1, max_length=30)
    receipt_date: date
    lines: list[_GRNLine] = Field(min_length=1, max_length=200)


class ExtractedVendor(_Strict):
    vendor_code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=200)
    tax_id: str | None = Field(default=None, max_length=40)
    bank_account: str | None = Field(default=None, max_length=60)
    bank_name: str | None = Field(default=None, max_length=100)


_MODELS = {"invoice": ExtractedInvoice, "purchase_order": ExtractedPO, "goods_receipt": ExtractedGRN, "vendor_record": ExtractedVendor}


def validate_structured(doc_type: str, data: dict) -> dict:
    """Validate and normalise. Raises pydantic.ValidationError."""
    return _MODELS[doc_type].model_validate(data).model_dump()


def safe_errors(exc: ValidationError) -> list[dict]:
    """Error locations/types only: never echo the submitted values (they may be sensitive)."""
    return [{"field": ".".join(str(p) for p in e["loc"]), "type": e["type"]} for e in exc.errors()]
