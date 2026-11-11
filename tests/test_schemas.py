from datetime import date
from decimal import Decimal as D

import pytest

pytest.importorskip("pydantic")
from backend.schemas.extraction import ExtractedInvoice, ValidationError, safe_errors, validate_structured  # noqa: E402

LINE = {"line_no": 1, "description": "Chair", "quantity": D("2"), "unit_price": D("10.00"), "discount_pct": D("0"),
        "tax_rate": D("0.1"), "line_total": D("20.00"), "tax_amount": D("2.00")}


def test_valid_invoice_passes_and_keeps_decimals():
    out = validate_structured("invoice", {"invoice_number": "INV-1", "currency": "USD", "invoice_date": date(2026, 1, 2),
                                          "grand_total": D("22.00"), "lines": [LINE]})
    assert out["grand_total"] == D("22.00") and isinstance(out["lines"][0]["unit_price"], D)


def test_missing_business_fields_are_allowed_but_floats_and_extras_are_not():
    assert validate_structured("invoice", {"lines": []})["invoice_number"] is None
    with pytest.raises(ValidationError):
        validate_structured("invoice", {"grand_total": 10.5, "lines": []})
    with pytest.raises(ValidationError):
        validate_structured("invoice", {"unexpected": "x", "lines": []})


def test_ranges_and_formats_enforced():
    for bad in ({"currency": "usd"}, {"currency": "US"}, {"lines": [{**LINE, "quantity": D("-1")}]}, {"lines": [{**LINE, "tax_rate": D("5")}]}):
        with pytest.raises(ValidationError):
            ExtractedInvoice.model_validate({"lines": [], **bad})


def test_safe_errors_never_echo_submitted_values():
    with pytest.raises(ValidationError) as e:
        validate_structured("invoice", {"currency": "SECRET-VALUE", "lines": []})
    assert "SECRET" not in str(safe_errors(e.value)) and safe_errors(e.value)[0]["field"] == "currency"
