"""Matching Service entry point (pure Python, no LLM, no database)."""
from __future__ import annotations

from dataclasses import dataclass, field

from backend.services.arithmetic import check_arithmetic
from backend.services.duplicates import detect_duplicates
from backend.services.po_matching import match_invoice
from backend.services.rules import Finding, Tolerances
from backend.services.validation import validate_fields


@dataclass
class EvaluationResult:
    findings: list[Finding] = field(default_factory=list)
    match_mode: str = "none"

    @property
    def result(self) -> str:
        if any(f.outcome == "fail" for f in self.findings):
            return "fail"
        return "warning" if self.findings else "pass"

    @property
    def rule_ids(self) -> set[str]:
        return {f.rule_id for f in self.findings}


def evaluate_invoice(invoice: dict, *, vendor: dict | None = None, po: dict | None = None, grn: dict | None = None,
                     prior_invoices=(), tolerances: Tolerances | None = None, three_way: bool = True) -> EvaluationResult:
    tol = tolerances or Tolerances()
    res = EvaluationResult()
    res.findings += validate_fields(invoice, vendor)
    res.findings += check_arithmetic(invoice, tol)
    match_findings, res.match_mode = match_invoice(invoice, po, grn, vendor, tol, three_way)
    res.findings += match_findings
    res.findings += detect_duplicates(invoice, prior_invoices, tol)
    return res
