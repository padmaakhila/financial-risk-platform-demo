"""Two-way (invoice vs PO) and three-way (invoice vs PO vs GRN) matching. Deterministic."""
from __future__ import annotations

from decimal import Decimal

from backend.services.rules import Finding, Tolerances, make_finding

HUNDRED = Decimal(100)


def _desc_matches(inv_desc: str, po_desc: str) -> bool:
    a, b = (inv_desc or "").casefold().strip(), (po_desc or "").casefold().strip()
    return bool(b) and (b in a or a in b)  # containment tolerates extra text on the invoice line


def match_invoice(inv: dict, po: dict | None, grn: dict | None, vendor: dict | None, tol: Tolerances,
                  three_way: bool = True) -> tuple[list[Finding], str]:
    """Return (findings, mode_used). mode is 'two_way', 'three_way', or 'none' when the PO is missing.
    If the PO is missing the GRN check is skipped (a GRN is only meaningful against its PO)."""
    f: list[Finding] = []
    if po is None:
        f.append(make_finding("MATCH_MISSING_PO", "No purchase order found for this invoice", expected="existing PO",
                              actual=inv.get("po_number") or "no PO number on invoice", evidence={"po_number": inv.get("po_number")}))
        return f, "none"
    if inv.get("vendor_code") != po.get("vendor_code"):
        f.append(make_finding("MATCH_VENDOR", "Invoice vendor differs from PO vendor", expected=po.get("vendor_code"),
                              actual=inv.get("vendor_code"), evidence={"po_number": po["po_number"]}))
    po_lines = {l["line_no"]: l for l in po["lines"]}
    grn_lines = {l["po_line_no"]: l for l in (grn or {}).get("lines", [])}
    mode = "three_way" if three_way else "two_way"

    for il in inv.get("lines") or []:
        n = il["line_no"]
        pl = po_lines.get(n)
        loc = {"line_no": n, "po_number": po["po_number"]}
        if pl is None or not _desc_matches(il.get("description"), pl["description"]):
            f.append(make_finding("MATCH_ITEM", f"Invoice line {n} does not correspond to a PO line",
                                  expected=pl["description"] if pl else "a line on the PO", actual=il.get("description"), evidence=loc))
            continue
        if il["unit_price"] is not None:
            pct = abs(il["unit_price"] - pl["unit_price"]) / pl["unit_price"] * HUNDRED if pl["unit_price"] else Decimal(0)
            if pct > tol.price_tolerance_pct:
                f.append(make_finding("MATCH_PRICE", f"Line {n} unit price differs from PO by {pct.quantize(Decimal('0.01'))}%",
                                      expected=pl["unit_price"], actual=il["unit_price"], difference=il["unit_price"] - pl["unit_price"],
                                      pct=pct, evidence={**loc, "tolerance_pct": str(tol.price_tolerance_pct)}))
        allowed_po = pl["quantity"] * (1 + tol.qty_tolerance_pct / HUNDRED)
        if il["quantity"] > allowed_po:
            f.append(make_finding("MATCH_QTY_PO", f"Line {n} quantity exceeds ordered quantity", expected=pl["quantity"],
                                  actual=il["quantity"], difference=il["quantity"] - pl["quantity"],
                                  ratio=il["quantity"] / pl["quantity"] if pl["quantity"] else None, evidence=loc))
        if il.get("tax_rate") is not None and il["tax_rate"] != pl["tax_rate"]:
            f.append(make_finding("MATCH_TAX_RATE", f"Line {n} tax rate differs from PO", expected=pl["tax_rate"],
                                  actual=il["tax_rate"], evidence=loc))

    if mode == "three_way":
        if grn is None or grn.get("po_number") != po["po_number"]:
            why = "No goods receipt found" if grn is None else "Goods receipt belongs to a different PO"
            f.append(make_finding("MATCH_MISSING_GRN", f"{why} for this invoice", expected="GRN for this PO",
                                  actual=inv.get("grn_number") or "no GRN number on invoice",
                                  evidence={"grn_number": inv.get("grn_number"), "po_number": po["po_number"]}))
        else:
            partial = []
            for il in inv.get("lines") or []:
                n, pl = il["line_no"], po_lines.get(il["line_no"])
                if pl is None:
                    continue
                gl = grn_lines.get(n)
                received = gl["quantity_received"] if gl else Decimal(0)
                if il["quantity"] > received * (1 + tol.qty_tolerance_pct / HUNDRED):
                    f.append(make_finding("MATCH_QTY_GRN", f"Line {n} quantity exceeds received quantity", expected=received,
                                          actual=il["quantity"], difference=il["quantity"] - received,
                                          ratio=il["quantity"] / received if received else Decimal(99),
                                          evidence={"line_no": n, "grn_number": grn["grn_number"]}))
                elif received < pl["quantity"]:
                    partial.append({"line_no": n, "ordered": str(pl["quantity"]), "received": str(received), "invoiced": str(il["quantity"])})
            if partial:
                f.append(make_finding("MATCH_PARTIAL_GRN", "Goods only partly received; invoice bills the received quantity",
                                      expected="full receipt", actual="partial receipt",
                                      evidence={"lines": partial, "grn_number": grn["grn_number"]}))
    return f, mode
