"""Shared types for the deterministic Matching Service: tolerances, findings, severity rules."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

D = Decimal


@dataclass(frozen=True)
class Tolerances:
    price_tolerance_pct: Decimal = D("1.00")
    qty_tolerance_pct: Decimal = D("0.00")
    amount_tolerance_abs: Decimal = D("0.01")
    duplicate_threshold: Decimal = D("0.85")

    @classmethod
    def from_mapping(cls, m: dict) -> "Tolerances":
        base = cls()
        return cls(**{f: D(str(m[f])) if f in m else getattr(base, f) for f in base.__dataclass_fields__})


EXCEPTION_TYPES = {
    "ARITH": "arithmetic", "MATCH": "matching", "DUP": "duplicate", "VAL": "validation",
    "SEC": "security", "DOC": "document",
}


@dataclass
class Finding:
    rule_id: str
    severity: str
    outcome: str  # "fail" | "warning"
    message: str
    expected: str | None = None
    actual: str | None = None
    difference: str | None = None
    evidence: dict = field(default_factory=dict)

    def to_dict(self, finding_id: int) -> dict:
        """JSON-safe shape used by agents and the workflow state (no Decimals)."""
        return {"id": finding_id, "rule_id": self.rule_id, "severity": self.severity, "outcome": self.outcome, "message": self.message,
                "expected": self.expected, "actual": self.actual, "difference": self.difference, "evidence": self.evidence}

    @property
    def exception_type(self) -> str:
        return EXCEPTION_TYPES[self.rule_id.split("_", 1)[0]]


def severity_for(rule_id: str, *, diff: Decimal | None = None, pct: Decimal | None = None, ratio: Decimal | None = None) -> str:
    """Deterministic severity table. The LLM never decides severity."""
    if rule_id.startswith("ARITH"):
        d = abs(diff or D(0))
        return "low" if d <= D("1.00") else "medium" if d <= D("50") else "high" if d <= D("500") else "critical"
    if rule_id == "MATCH_PRICE":
        p = abs(pct or D(0))
        return "medium" if p <= D(5) else "high" if p <= D(20) else "critical"
    if rule_id in ("MATCH_QTY_PO", "MATCH_QTY_GRN"):
        return "critical" if (ratio or D(0)) >= D(2) else "high"
    if rule_id in ("DUP_FUZZY",):
        return "high" if (ratio or D(0)) >= D("0.95") else "medium"
    return {
        "MATCH_MISSING_PO": "high", "MATCH_MISSING_GRN": "medium", "MATCH_PARTIAL_GRN": "low",
        "MATCH_VENDOR": "high", "MATCH_ITEM": "medium", "MATCH_TAX_RATE": "medium",
        "DUP_EXACT": "high", "VAL_TAX_ID": "medium", "VAL_BANK_FORMAT": "high", "VAL_BANK_MISMATCH": "critical", "VAL_VENDOR_REJECTED": "critical",
        "VAL_MISSING_FIELD": "medium", "SEC_PROMPT_INJECTION": "high", "DOC_LOW_CONF": "low",
        "DOC_UNREADABLE": "medium", "DOC_UNSUPPORTED_TYPE": "low",
    }[rule_id]


WARNING_RULES = {"MATCH_PARTIAL_GRN", "DOC_LOW_CONF", "SEC_PROMPT_INJECTION"}


def make_finding(rule_id: str, message: str, *, expected=None, actual=None, difference=None, evidence=None,
                 diff=None, pct=None, ratio=None) -> Finding:
    s = lambda v: None if v is None else str(v)
    return Finding(rule_id=rule_id, severity=severity_for(rule_id, diff=diff, pct=pct, ratio=ratio),
                   outcome="warning" if rule_id in WARNING_RULES else "fail", message=message,
                   expected=s(expected), actual=s(actual), difference=s(difference), evidence=evidence or {})
