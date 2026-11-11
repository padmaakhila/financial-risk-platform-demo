"""Duplicate-invoice detection: exact match first, then a documented weighted fuzzy score.

Score = 0.30*invoice_number + 0.20*vendor + 0.25*amount + 0.15*date + 0.10*po_number
  invoice_number: Indel similarity of normalised numbers (upper-case, alphanumerics only, letter O read as zero)
  vendor:         1.0 when the vendor record is the same, else token-sort similarity of normalised names
  amount:         1.0 when grand totals are equal, falling linearly to 0 at a 10% difference
  date:           1.0 for the same date, falling linearly to 0 at 14 days apart
  po_number:      1.0 when both invoices cite the same PO, else 0
A fuzzy hit is only a SUSPICION for human review, never proof of fraud. Only invoices that
arrived earlier (lower seq) are compared, so the original is never flagged because of its copy.
"""
from __future__ import annotations

import re
from decimal import Decimal

from backend.services.rules import Finding, Tolerances, make_finding

try:  # RapidFuzz is the intended engine; difflib keeps the code runnable if it is missing.
    from rapidfuzz import fuzz as _fuzz

    def _indel(a: str, b: str) -> float:
        return _fuzz.ratio(a, b) / 100.0

    def _token_sort(a: str, b: str) -> float:
        return _fuzz.token_sort_ratio(a, b) / 100.0
    ENGINE = "rapidfuzz"
except ImportError:  # pragma: no cover
    from difflib import SequenceMatcher

    def _indel(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()

    def _token_sort(a: str, b: str) -> float:
        return _indel(" ".join(sorted(a.split())), " ".join(sorted(b.split())))
    ENGINE = "difflib"

WEIGHTS = {"invoice_number": 0.30, "vendor": 0.20, "amount": 0.25, "date": 0.15, "po_number": 0.10}
_LEGAL = {"ltd", "inc", "llc", "gmbh", "co", "limited", "incorporated", "corp", "corporation"}


def normalize_vendor(name: str | None) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", (name or "").casefold()).split()
    return " ".join(w for w in words if w not in _LEGAL)


def normalize_number(number: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (number or "").upper()).replace("O", "0")


def exact_key(inv: dict) -> tuple | None:
    number = (inv.get("invoice_number") or "").strip().casefold()
    return (inv.get("vendor_code"), number) if number else None


def similarity_signals(inv: dict, other: dict) -> dict:
    same_vendor = inv.get("vendor_code") is not None and inv.get("vendor_code") == other.get("vendor_code")
    vendor = 1.0 if same_vendor else _token_sort(normalize_vendor(inv.get("vendor_name_raw")), normalize_vendor(other.get("vendor_name_raw")))
    a, b = inv.get("grand_total"), other.get("grand_total")
    if a is None or b is None:
        amount = 0.0
    elif a == b:
        amount = 1.0
    else:
        rel = abs(a - b) / max(abs(a), abs(b), Decimal("0.01"))
        amount = max(0.0, 1.0 - float(rel) * 10)
    d1, d2 = inv.get("invoice_date"), other.get("invoice_date")
    date = 0.0 if d1 is None or d2 is None else max(0.0, 1.0 - abs((d1 - d2).days) / 14)
    po = 1.0 if inv.get("po_number") and inv.get("po_number") == other.get("po_number") else 0.0
    return {"invoice_number": _indel(normalize_number(inv.get("invoice_number")), normalize_number(other.get("invoice_number"))),
            "vendor": vendor, "amount": amount, "date": date, "po_number": po}


def weighted_score(signals: dict) -> float:
    return sum(WEIGHTS[k] * signals[k] for k in WEIGHTS)


def detect_duplicates(inv: dict, prior_invoices, tol: Tolerances) -> list[Finding]:
    findings: list[Finding] = []
    key = exact_key(inv)
    flagged: set = set()
    for other in prior_invoices:
        if other.get("seq", 0) >= inv.get("seq", 1 << 60) or other is inv:
            continue
        if key and exact_key(other) == key:
            findings.append(make_finding("DUP_EXACT", "Same vendor and invoice number as an earlier invoice",
                                         expected="unique vendor + invoice number", actual=f"{inv['invoice_number']} (also {other['invoice_number']})",
                                         evidence={"related_invoice_seq": other.get("seq"), "related_invoice_id": other.get("id"),
                                                   "signals": {"vendor_and_number_identical": True}}))
            flagged.add(id(other))
    best: dict | None = None
    for other in prior_invoices:
        if other.get("seq", 0) >= inv.get("seq", 1 << 60) or other is inv or id(other) in flagged:
            continue
        sig = similarity_signals(inv, other)
        score = weighted_score(sig)
        if score >= float(tol.duplicate_threshold) and (best is None or score > best["score"]):
            best = {"score": score, "signals": sig, "other": other}
    if best:
        o = best["other"]
        findings.append(make_finding("DUP_FUZZY", f"Suspected duplicate of {o.get('invoice_number')} (similarity {best['score']:.2f}); needs human review",
                                     expected=f"similarity below {tol.duplicate_threshold}", actual=f"{best['score']:.3f}",
                                     ratio=Decimal(str(round(best["score"], 4))),
                                     evidence={"related_invoice_seq": o.get("seq"), "related_invoice_id": o.get("id"),
                                               "score": round(best["score"], 4), "threshold": str(tol.duplicate_threshold),
                                               "weights": WEIGHTS, "signals": {k: round(v, 4) for k, v in best["signals"].items()},
                                               "engine": ENGINE}))
    return findings
