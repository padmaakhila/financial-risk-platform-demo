"""Shared helpers for agent/workflow tests (pure Python, no database)."""
import json

from backend.services.matching import evaluate_invoice
from backend.services.rules import Tolerances
from scripts.generate_data import build_dataset

DS = build_dataset(42)
VENDORS = {v["vendor_code"]: v for v in DS["vendors"]}
POS = {p["po_number"]: p for p in DS["purchase_orders"]}
GRNS = {g["grn_number"]: g for g in DS["goods_receipts"]}
FIRST = {}
for _i in DS["invoices"]:
    FIRST.setdefault(_i["scenario_code"], _i)


def evaluate(inv, priors=()):
    return evaluate_invoice(inv, vendor=VENDORS[inv["vendor_code"]], po=POS.get(inv["po_number"]), grn=GRNS.get(inv["grn_number"]),
                            prior_invoices=priors, tolerances=Tolerances())


def priors_for(inv):
    return [o for o in DS["invoices"] if o["seq"] < inv["seq"] and (o["vendor_code"] == inv["vendor_code"] or o["grand_total"] == inv["grand_total"])]


def findings_of(code):
    inv = FIRST[code]
    res = evaluate(inv, priors_for(inv))
    return inv, [f.to_dict(i) for i, f in enumerate(res.findings, 100)]


def summary_of(inv):
    return {k: (str(inv[k]) if inv[k] is not None else None) for k in ("invoice_number", "vendor_name_raw", "currency", "subtotal", "tax_total", "grand_total")}


def good_reply(findings, summary="Automated checks found issues that need review."):
    """A model reply that cites every finding using only values from that finding."""
    return json.dumps({"summary": summary, "items": [{"finding_id": f["id"], "explanation": f"{f['message']}."} for f in findings], "caveats": []})
