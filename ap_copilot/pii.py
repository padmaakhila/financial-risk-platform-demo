"""PII / secret handling. Pure functions, no third-party imports."""
from __future__ import annotations

import re
from typing import Any, Optional

REDACTED = "[REDACTED]"

_JWT = re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}")
_DBURL = re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s/:@]+:[^\s/@]+@\S+")
_SECRET_KV = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|api[_\- ]?key|access[_\- ]?token|token|"
    r"authorization|jwt[_\- ]?secret|database[_\- ]?url)\b\s*[:=]\s*\S+"
)
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
# 9-20 digit runs that are not part of a decimal amount
_LONG_DIGITS = re.compile(r"(?<![\w.,\-])\d{9,20}(?!\d|[.,]\d)")

_PATTERNS = (_JWT, _BEARER, _DBURL, _SECRET_KV, _IBAN, _LONG_DIGITS)


def contains_sensitive(text: Any) -> bool:
    if not isinstance(text, str):
        return False
    return any(p.search(text) for p in _PATTERNS)


def redact_text(text: Any) -> str:
    """Replace tokens, secrets, connection strings and account-like numbers."""
    if text is None:
        return ""
    s = str(text)
    for p in _PATTERNS:
        s = p.sub(REDACTED, s)
    return s


def mask_value(value: Any) -> Optional[str]:
    """Mask a bank account using the platform's own ``mask_account`` helper.
    Never returns the full value, even if the helper is unavailable."""
    if value is None or str(value).strip() == "":
        return None
    s = str(value)
    try:
        from backend.auth.permissions import mask_account
        masked = str(mask_account(s))
        if masked and masked != s:
            return masked
    except Exception:  # defensive: fall through to local masking
        pass
    return "****" + s[-4:] if len(s) > 4 else "****"


_BANKISH = re.compile(r"(?i)(bank|iban|account|acct|swift|routing|ifsc)")


def is_bank_field(name: Any) -> bool:
    return bool(_BANKISH.search(str(name or "")))
