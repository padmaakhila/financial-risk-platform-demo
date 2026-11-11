"""Create the files used in docs/DEMO_SCRIPT.md in data/demo/.   python -m scripts.make_demo_documents
 demo_success_invoice.pdf   new invoice number, same lines/prices as a seeded PO+GRN -> should pass every check
 demo_failure_invoice.pdf   exact duplicate of a seeded invoice AND a wrong tax amount -> DUP_EXACT + ARITH_TAX
 demo_scanned_invoice.pdf   a scanned-style copy of the success invoice (needs Tesseract)
 demo_unreadable_scan.pdf   noise-damaged scan -> manual entry
 demo_invalid.exe / demo_fake.pdf   rejected at upload with clear messages"""
from __future__ import annotations

import random
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

from backend.core.config import BASE_DIR
from backend.services.doc_text import invoice_lines_text
from scripts.generate_data import build_dataset, money, recompute
from scripts.generate_documents import write_digital_pdf, write_scanned_pdf


def build_demo_invoices(ds: dict) -> dict:
    originals_of_dups = {t["expected"]["duplicate_of_seq"] for t in ds["ground_truth"] if t["scenario_code"] in ("S02_DUP_EXACT", "S03_DUP_FUZZY")}
    pos = {p["po_number"] for p in ds["purchase_orders"]}
    grns = {g["grn_number"] for g in ds["goods_receipts"]}
    clean = [i for i in ds["invoices"] if i["scenario_code"] == "S01_CLEAN" and i["seq"] not in originals_of_dups and i["po_number"] in pos and i["grn_number"] in grns
             and i["document_kind"] == "digital_pdf"]
    a, b = clean[0], clean[1]
    success = deepcopy(a)
    success.update(invoice_number="DEMO-0001", invoice_date=a["invoice_date"] + timedelta(days=20), notes="", document_kind="digital_pdf")
    success["due_date"] = success["invoice_date"] + timedelta(days=30)
    failure = deepcopy(b)  # same vendor + same invoice number as seeded invoice B => exact duplicate
    failure["lines"][0]["tax_amount"] = money(failure["lines"][0]["tax_amount"] + 7)
    failure["tax_total"] = money(sum(l["tax_amount"] for l in failure["lines"]))
    failure["grand_total"] = money(failure["subtotal"] + failure["tax_total"])
    return {"success": success, "failure": failure, "duplicate_of": b}


def main() -> None:
    ds = build_dataset(42)
    demo = build_demo_invoices(ds)
    out = BASE_DIR / "data" / "demo"
    out.mkdir(parents=True, exist_ok=True)
    write_digital_pdf(out / "demo_success_invoice.pdf", invoice_lines_text(demo["success"]))
    write_digital_pdf(out / "demo_failure_invoice.pdf", invoice_lines_text(demo["failure"]))
    rng = random.Random(1)
    write_scanned_pdf(out / "demo_scanned_invoice.pdf", invoice_lines_text(demo["success"]), "good", rng)
    write_scanned_pdf(out / "demo_unreadable_scan.pdf", invoice_lines_text(demo["success"]), "unreadable", rng)
    (out / "demo_invalid.exe").write_bytes(b"MZ\x90\x00 synthetic non-document")
    (out / "demo_fake.pdf").write_bytes(b"MZ\x90\x00 pretends to be a PDF")
    print(f"Demo files written to {out}")
    print(f"  success invoice : {demo['success']['invoice_number']} (PO {demo['success']['po_number']}, GRN {demo['success']['grn_number']})")
    print(f"  failure invoice : {demo['failure']['invoice_number']} duplicates a seeded invoice and has a wrong tax amount")


if __name__ == "__main__":
    main()
