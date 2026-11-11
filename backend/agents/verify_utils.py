"""Helpers for deterministic verification of LLM text: number extraction and normalisation."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Numbers that stand alone. Digits inside identifiers (INV-000123), dates (2026-09-01) and times (10:30) are ignored.
NUM_RE = re.compile(r"(?<![\w.:])(?<!\w-)[$€£]?\d[\d,]*(?:\.\d+)?%?(?![\w:-])")
PAGE_RE = re.compile(r"\bpages?\s+(\d+)\b", re.I)


def norm(token: str) -> str | None:
    t = token.strip().lstrip("$€£").rstrip("%").replace(",", "")
    try:
        d = Decimal(t)
    except InvalidOperation:
        return None
    s = format(d.normalize(), "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def numbers_in(*texts) -> set[str]:
    out = set()
    for t in texts:
        for m in NUM_RE.finditer(str(t or "")):
            n = norm(m.group(0))
            if n is not None:
                out.add(n)
    return out


def leaf_numbers(obj) -> set[str]:
    """Numbers found in any scalar nested inside dicts/lists."""
    if isinstance(obj, dict):
        return set().union(*[leaf_numbers(v) for v in obj.values()]) if obj else set()
    if isinstance(obj, (list, tuple)):
        return set().union(*[leaf_numbers(v) for v in obj]) if obj else set()
    if isinstance(obj, bool) or obj is None:
        return set()
    if isinstance(obj, (int, Decimal)):
        n = norm(str(obj))
        return {n} if n is not None else set()
    return numbers_in(obj)


def strip_pages(text: str) -> str:
    return PAGE_RE.sub("", text)
