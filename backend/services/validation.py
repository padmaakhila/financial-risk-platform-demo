"""Deterministic field validation: formats, mandatory fields, vendor bank data, prompt-injection scan."""
from __future__ import annotations

import re

from backend.core.constants import BANK_ACCOUNT_REGEX, TAX_ID_REGEX
from backend.services.rules import Finding, make_finding

MANDATORY_FIELDS = ("invoice_number", "vendor_name_raw", "invoice_date", "currency", "grand_total")

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+(instructions|rules)",
    r"disregard\s+(all\s+)?(the\s+)?(rules|instructions)",
    r"\bsystem\s*:",
    r"you\s+are\s+now\b",
    r"reveal\s+(your\s+)?(system\s+)?prompt",
    r"\bapprove\s+(this\s+)?invoice\b",
    r"\b(post|release|make|send)\s+(a\s+|the\s+)?payment\s+(now|immediately|today)\b",
    r"\bimmediate\s+payment\b",
    r"mark\s+(all\s+)?(exceptions?|findings?)\s+as\s+(resolved|approved)",
    r"set\s+the\s+grand\s+total",
]
_INJECTION_RE = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)


def neutralize_injection(text: str | None) -> str:
    """Replace instruction-like phrases so they cannot steer a model (used before any LLM prompt)."""
    return _INJECTION_RE.sub("[instruction-like text removed]", text or "")


def scan_for_injection(text: str | None) -> str | None:
    """Return the matching snippet or None. Document text is DATA, never instructions."""
    if not text:
        return None
    m = _INJECTION_RE.search(text)
    return text[max(0, m.start() - 20): m.end() + 20] if m else None


def validate_fields(inv: dict, vendor: dict | None) -> list[Finding]:
    out: list[Finding] = []
    for name in MANDATORY_FIELDS:
        if inv.get(name) in (None, ""):
            out.append(make_finding("VAL_MISSING_FIELD", f"Mandatory field '{name}' is missing",
                                    expected="a value", actual="missing", evidence={"field": name}))
    tax = inv.get("vendor_tax_id_raw")
    if tax and not re.fullmatch(TAX_ID_REGEX, tax):
        out.append(make_finding("VAL_TAX_ID", "Vendor tax ID does not match the expected format",
                                expected=TAX_ID_REGEX, actual=tax, evidence={"field": "vendor_tax_id_raw"}))
    bank = inv.get("bank_account_raw")
    if bank:
        if not re.fullmatch(BANK_ACCOUNT_REGEX, bank):
            out.append(make_finding("VAL_BANK_FORMAT", "Bank account does not match the expected format",
                                    expected=BANK_ACCOUNT_REGEX, actual=bank, evidence={"field": "bank_account_raw"}))
        elif vendor and vendor.get("bank_account") and vendor["bank_account"] != bank:
            out.append(make_finding("VAL_BANK_MISMATCH", "Invoice bank account differs from the vendor master record",
                                    expected=vendor["bank_account"], actual=bank, evidence={"field": "bank_account_raw"}))
    texts = [("notes", inv.get("notes")), ("vendor_name_raw", inv.get("vendor_name_raw"))]
    texts += [(f"lines[{l['line_no']}].description", l.get("description")) for l in inv.get("lines") or []]
    hits = [(loc, snip) for loc, t in texts if (snip := scan_for_injection(t))]
    if hits:
        out.append(make_finding("SEC_PROMPT_INJECTION", "Document text contains instruction-like content; it is treated as data only",
                                expected="plain business text", actual=hits[0][1],
                                evidence={"locations": [h[0] for h in hits], "snippets": [h[1] for h in hits][:3]}))
    return out
