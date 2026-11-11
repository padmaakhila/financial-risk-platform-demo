"""PII redaction and untrusted-text sanitising for anything that reaches an LLM prompt."""
from __future__ import annotations

import re

from backend.services.validation import neutralize_injection

_PATTERNS = [
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"), "[BANK_ACCOUNT]"),
    (re.compile(r"\bTX\d{9}\b"), "[TAX_ID]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"\+\d[\d\s().-]{7,}\d|\(\d{3}\)\s?\d{3}[-\s]?\d{4}"), "[PHONE]"),
]
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def redact_text(text: str | None) -> str:
    out = text or ""
    for rx, token in _PATTERNS:
        out = rx.sub(token, out)
    return out


def sanitize_untrusted(text: str | None, max_len: int = 200) -> str:
    """Document text is DATA. Strip control characters and delimiter-like characters, neutralise
    instruction-like phrases, redact PII, collapse whitespace and truncate."""
    t = _CONTROL.sub(" ", text or "")
    t = t.replace("<", " ").replace(">", " ").replace("`", "'")
    t = neutralize_injection(t)
    t = redact_text(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_len]
