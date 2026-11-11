from backend.services.extraction import extract_document
from backend.services.matching import evaluate_invoice
from backend.services.rules import Tolerances
from scripts.generate_data import build_dataset
from scripts.make_demo_documents import build_demo_invoices
from backend.services.doc_text import invoice_lines_text
from scripts.generate_documents import write_digital_pdf

DS = build_dataset(42)
VENDORS = {v["vendor_code"]: v for v in DS["vendors"]}
BY_TAX = {v["tax_id"]: v for v in DS["vendors"]}
POS = {p["po_number"]: p for p in DS["purchase_orders"]}
GRNS = {g["grn_number"]: g for g in DS["goods_receipts"]}


def process_like_the_platform(path, seq):
    """extract -> resolve vendor by tax id (as extraction_db does) -> evaluate against the seeded database state."""
    r = extract_document(path, validator=lambda t, d: d)
    inv = {**r.data, "seq": seq, "vendor_code": BY_TAX[r.data["vendor_tax_id_raw"]]["vendor_code"]}
    priors = [i for i in DS["invoices"] if i["vendor_code"] == inv["vendor_code"] or i["grand_total"] == inv["grand_total"]]
    return r, evaluate_invoice(inv, vendor=VENDORS[inv["vendor_code"]], po=POS.get(inv["po_number"]), grn=GRNS.get(inv["grn_number"]), prior_invoices=priors, tolerances=Tolerances())


def test_demo_success_invoice_passes_every_check(tmp_path):
    demo = build_demo_invoices(DS)
    p = tmp_path / "s.pdf"
    write_digital_pdf(p, invoice_lines_text(demo["success"]))
    r, res = process_like_the_platform(p, seq=10_000)
    assert r.status == "ok" and r.data["invoice_number"] == "DEMO-0001"
    assert res.result == "pass" and not res.findings


def test_demo_failure_invoice_is_a_duplicate_with_a_wrong_tax(tmp_path):
    demo = build_demo_invoices(DS)
    p = tmp_path / "f.pdf"
    write_digital_pdf(p, invoice_lines_text(demo["failure"]))
    r, res = process_like_the_platform(p, seq=10_001)
    assert res.rule_ids == {"DUP_EXACT", "ARITH_TAX"} and res.result == "fail"
    dup = next(f for f in res.findings if f.rule_id == "DUP_EXACT")
    assert dup.evidence["related_invoice_seq"] == demo["duplicate_of"]["seq"]
