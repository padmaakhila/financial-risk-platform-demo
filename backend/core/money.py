"""Exact money helpers. Floats are rejected everywhere in financial code."""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")


def money(value) -> Decimal:
    """Round to 2 places, half-up (documented currency rounding rule)."""
    return to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def to_decimal(value) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("floats/bools are not allowed for financial values")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite decimal")
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        return parse_decimal(value)
    raise TypeError(f"unsupported type for decimal: {type(value).__name__}")


def parse_decimal(text: str) -> Decimal:
    """Parse '$1,234.56', '1.234,56', '12,50', '(45.00)'. Raises ValueError if not a number."""
    s = re.sub(r"[\s$€£¥]|USD|EUR|GBP", "", text.strip(), flags=re.I)
    negative = s.startswith("(") and s.endswith(")") or s.startswith("-")
    s = s.strip("()-")
    if not s or not re.fullmatch(r"[\d.,]+", s):
        raise ValueError(f"not a number: {text!r}")
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
    elif "," in s:
        dec = "," if re.search(r",\d{1,2}$", s) and s.count(",") == 1 else None
    else:
        dec = "." if s.count(".") == 1 else None
    if dec is None:
        s = s.replace(",", "").replace(".", "") if s.count(".") > 1 or "," in s else s
    else:
        other = "." if dec == "," else ","
        s = s.replace(other, "").replace(dec, ".")
    try:
        value = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {text!r}") from exc
    return -value if negative else value
