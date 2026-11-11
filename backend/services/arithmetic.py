"""Deterministic arithmetic validation using Decimal. Nothing here calls an LLM."""
from __future__ import annotations

from decimal import Decimal

from backend.core.money import money
from backend.services.rules import Finding, Tolerances, make_finding

HUNDRED = Decimal(100)


def check_arithmetic(inv: dict, tol: Tolerances) -> list[Finding]:
    """Each rule compares a STATED value with a value recomputed from other stated values.
    Rounding: half-up to 2 decimals. Differences within amount_tolerance_abs pass."""
    findings: list[Finding] = []

    def compare(rule, label, locator, stated, expected, line_no=None):
        diff = money(stated) - money(expected)
        if abs(diff) > tol.amount_tolerance_abs:
            findings.append(make_finding(
                rule, f"{label} is {money(stated)} but recalculation gives {money(expected)}",
                expected=money(expected), actual=money(stated), difference=diff, diff=diff,
                evidence={"field": locator, "line_no": line_no, "recalculated_by": rule}))

    lines = inv.get("lines") or []
    for ln in lines:
        n = ln["line_no"]
        if None not in (ln.get("quantity"), ln.get("unit_price"), ln.get("discount_pct"), ln.get("line_total")):
            expected = money(ln["quantity"] * ln["unit_price"] * (HUNDRED - ln["discount_pct"]) / HUNDRED)
            compare("ARITH_LINE_TOTAL", f"Line {n} total", f"lines[{n}].line_total", ln["line_total"], expected, n)
        if None not in (ln.get("line_total"), ln.get("tax_rate"), ln.get("tax_amount")):
            compare("ARITH_TAX", f"Line {n} tax", f"lines[{n}].tax_amount", ln["tax_amount"], money(ln["line_total"] * ln["tax_rate"]), n)
    if lines and all(l.get("line_total") is not None for l in lines) and inv.get("subtotal") is not None:
        compare("ARITH_SUBTOTAL", "Subtotal", "subtotal", inv["subtotal"], sum((money(l["line_total"]) for l in lines), Decimal(0)))
    if lines and all(l.get("tax_amount") is not None for l in lines) and inv.get("tax_total") is not None:
        compare("ARITH_TAX", "Total tax", "tax_total", inv["tax_total"], sum((money(l["tax_amount"]) for l in lines), Decimal(0)))
    if None not in (inv.get("subtotal"), inv.get("tax_total"), inv.get("grand_total")):
        compare("ARITH_GRAND_TOTAL", "Grand total", "grand_total", inv["grand_total"], money(inv["subtotal"]) + money(inv["tax_total"]))
    return findings
