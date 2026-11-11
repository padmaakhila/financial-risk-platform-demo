import random
from datetime import date
from decimal import Decimal as D

import pytest

from backend.services.doc_text import grn_lines_text, invoice_lines_text, po_lines_text, vendor_lines_text
from backend.services.extraction import TesseractEngine, TextLine, extract_document
from scripts.generate_data import build_dataset
from scripts.generate_documents import write_digital_pdf, write_scanned_pdf

try:
    import pydantic  # noqa: F401
    VALIDATOR = None  # use the real Pydantic validator
except ImportError:  # pragma: no cover
    VALIDATOR = lambda doc_type, data: data

DS = build_dataset(42)
FIRST = {}
for _i in DS["invoices"]:
    FIRST.setdefault(_i["scenario_code"], _i)
HEADER = ["invoice_number", "vendor_name_raw", "vendor_tax_id_raw", "bank_account_raw", "invoice_date", "due_date",
          "po_number", "grn_number", "currency", "subtotal", "tax_total", "grand_total"]
LINE = ("quantity", "unit_price", "discount_pct", "tax_rate", "line_total", "tax_amount")


def digital(tmp_path, inv, name="x.pdf", lines=None):
    p = tmp_path / name
    write_digital_pdf(p, lines or invoice_lines_text(inv))
    return p


def test_digital_invoices_extract_exactly_for_many_scenarios(tmp_path):
    for code in ("S01_CLEAN", "S04_LINE_TOTAL", "S05_TAX_CALC", "S06_GRAND_TOTAL", "S07_PRICE_DIFF", "S12_PARTIAL_GRN", "S13_BAD_TAX_ID", "S15_MISSING_FIELDS"):
        inv = FIRST[code]
        r = extract_document(digital(tmp_path, inv), validator=VALIDATOR)
        assert r.status == "ok" and r.doc_type == "invoice" and r.document_kind == "digital_pdf" and r.mean_confidence == 1.0, code
        assert {k: r.data[k] for k in HEADER} == {k: inv[k] for k in HEADER}, code
        assert len(r.data["lines"]) == len(inv["lines"])
        for a, b in zip(r.data["lines"], inv["lines"]):
            assert all(a[k] == b[k] for k in LINE) and a["description"] == b["description"][:60].strip()


def test_every_field_has_confidence_method_page_and_source_snippet(tmp_path):
    r = extract_document(digital(tmp_path, FIRST["S01_CLEAN"]), validator=VALIDATOR)
    by = {f.name: f for f in r.fields}
    for name in HEADER[:1] + ["grand_total", "line_1"]:
        f = by[name]
        assert f.method == "pdf_text" and f.confidence == 1.0 and f.page == 1 and f.snippet and f.bbox and not f.low_confidence
    assert by["grand_total"].snippet.startswith("Grand total")
    assert by["invoice_date"].value_text == str(FIRST["S01_CLEAN"]["invoice_date"])


def test_missing_fields_stay_missing_not_invented(tmp_path):
    r = extract_document(digital(tmp_path, FIRST["S15_MISSING_FIELDS"]), validator=VALIDATOR)
    assert r.data["invoice_date"] is None and r.data["currency"] is None
    assert next(f for f in r.fields if f.name == "currency").method == "none"


def test_prompt_injection_text_is_extracted_as_data_only(tmp_path):
    inv = FIRST["S19_PROMPT_INJECTION"]
    r = extract_document(digital(tmp_path, inv), validator=VALIDATOR)
    assert r.status == "ok" and r.data["notes"] == inv["notes"] and r.data["grand_total"] == inv["grand_total"]


def test_po_grn_and_vendor_documents_are_classified_and_parsed(tmp_path):
    po, grn, vendor = DS["purchase_orders"][0], DS["goods_receipts"][0], DS["vendors"][0]
    for lines, kind in [(po_lines_text(po), "purchase_order"), (grn_lines_text(grn), "goods_receipt"), (vendor_lines_text(vendor), "vendor_record")]:
        p = tmp_path / f"{kind}.pdf"
        write_digital_pdf(p, lines)
        r = extract_document(p, validator=VALIDATOR)
        assert r.status == "ok" and r.doc_type == kind, (kind, r.reason)
    r = extract_document(tmp_path / "purchase_order.pdf", validator=VALIDATOR)
    assert r.data["po_number"] == po["po_number"] and r.data["order_date"] == po["order_date"] and len(r.data["lines"]) == len(po["lines"])
    r = extract_document(tmp_path / "goods_receipt.pdf", validator=VALIDATOR)
    assert r.data["grn_number"] == grn["grn_number"] and [l["quantity_received"] for l in r.data["lines"]] == [D(l["quantity_received"]) for l in grn["lines"]]


def test_garbage_and_hostile_files_never_crash(tmp_path):
    (tmp_path / "bad.pdf").write_bytes(b"%PDF-1.4 this is not really a pdf")
    r = extract_document(tmp_path / "bad.pdf")
    assert r.status in ("needs_manual_entry", "failed") and r.message
    (tmp_path / "x.png").write_bytes(b"\x89PNG\r\n\x1a\nnot an image")
    assert extract_document(tmp_path / "x.png").status == "failed"
    assert extract_document(tmp_path / "missing.pdf").status == "failed"
    (tmp_path / "x.csv").write_text("a,b\n1,2\n")
    assert extract_document(tmp_path / "x.csv").reason == "UNSUPPORTED_FOR_EXTRACTION"


def test_unknown_document_goes_to_manual_entry(tmp_path):
    p = tmp_path / "memo.pdf"
    write_digital_pdf(p, ["Lunch is at noon", "Bring your own plate", "See you there", "Thanks"])
    r = extract_document(p, validator=VALIDATOR)
    assert r.status == "needs_manual_entry" and r.reason == "UNKNOWN_DOCUMENT_TYPE"


def test_llm_values_are_accepted_only_if_present_in_source_text(tmp_path):
    inv = FIRST["S01_CLEAN"]
    lines = invoice_lines_text(inv)
    lines[0] = f"Document ref {inv['invoice_number']}"  # header the rule parser cannot read
    p = digital(tmp_path, inv, lines=lines)
    assert extract_document(p, validator=VALIDATOR).data["invoice_number"] is None
    ok = extract_document(p, validator=VALIDATOR, llm_extract=lambda text, missing: {"invoice_number": inv["invoice_number"]})
    f = next(f for f in ok.fields if f.name == "invoice_number")
    assert ok.data["invoice_number"] == inv["invoice_number"] and f.method == "llm_estimate" and f.confidence is None and f.low_confidence
    fake = extract_document(p, validator=VALIDATOR, llm_extract=lambda text, missing: {"invoice_number": "INV-999999"})
    assert fake.data["invoice_number"] is None and fake.rejected_llm_values == ["invoice_number"]
    boom = extract_document(p, validator=VALIDATOR, llm_extract=lambda text, missing: 1 / 0)
    assert boom.data["invoice_number"] is None


# ---- scanned path with a fake OCR engine (logic) --------------------------------------
class FakeEngine:
    def __init__(self, text_lines, confidences, available=True):
        self.text_lines, self.confidences, self.is_available, self.calls = text_lines, list(confidences), available, []

    def available(self):
        return self.is_available

    def read(self, image, profile, page):
        self.calls.append(profile)
        conf = self.confidences[min(len(self.calls) - 1, len(self.confidences) - 1)]
        return [TextLine(page, t, conf, "ocr_word_conf", (0, i * 20, 500, i * 20 + 18), len(t.split())) for i, t in enumerate(self.text_lines) if t.strip()]


def scan_pdf(tmp_path, inv, quality="good"):
    p = tmp_path / f"scan_{quality}.pdf"
    write_scanned_pdf(p, invoice_lines_text(inv), quality, random.Random(1))
    return p


def test_good_ocr_confidence_uses_one_attempt_and_flags_nothing(tmp_path):
    inv = FIRST["S01_CLEAN"]
    eng = FakeEngine(invoice_lines_text(inv), [0.95])
    r = extract_document(scan_pdf(tmp_path, inv), engine=eng, validator=VALIDATOR)
    assert r.status == "ok" and r.document_kind == "scanned_good" and eng.calls == ["default"] and not r.findings
    assert next(f for f in r.fields if f.name == "grand_total").method == "ocr_word_conf"


def test_low_confidence_retries_once_with_alternative_profile_then_warns(tmp_path):
    inv = FIRST["S01_CLEAN"]
    eng = FakeEngine(invoice_lines_text(inv), [0.55, 0.60])
    r = extract_document(scan_pdf(tmp_path, inv), engine=eng, validator=VALIDATOR)
    assert eng.calls == ["default", "alt"] and r.status == "ok" and r.document_kind == "scanned_low_quality"
    assert [f.rule_id for f in r.findings] == ["DOC_LOW_CONF"] and r.findings[0].outcome == "warning"
    assert all(f.low_confidence for f in r.fields if f.method == "ocr_word_conf" and f.value_text)


def test_retry_that_improves_confidence_is_used(tmp_path):
    inv = FIRST["S01_CLEAN"]
    eng = FakeEngine(invoice_lines_text(inv), [0.50, 0.92])
    r = extract_document(scan_pdf(tmp_path, inv), engine=eng, validator=VALIDATOR)
    assert [a["profile"] for a in r.attempts] == ["default", "alt"] and r.document_kind == "scanned_good" and not r.findings


def test_unreadable_scan_goes_to_manual_entry_with_finding(tmp_path):
    inv = FIRST["S16_UNREADABLE_SCAN"]
    eng = FakeEngine(invoice_lines_text(inv), [0.20])
    r = extract_document(scan_pdf(tmp_path, inv), engine=eng, validator=VALIDATOR)
    assert r.status == "needs_manual_entry" and r.reason == "UNREADABLE_SCAN" and len(eng.calls) == 2
    assert [f.rule_id for f in r.findings] == ["DOC_UNREADABLE"] and r.data is None


def test_missing_ocr_engine_degrades_gracefully(tmp_path):
    r = extract_document(scan_pdf(tmp_path, FIRST["S01_CLEAN"]), engine=FakeEngine([], [0.9], available=False))
    assert r.status == "needs_manual_entry" and r.reason == "OCR_UNAVAILABLE" and "README" in r.message


def test_ocr_engine_exceptions_are_contained(tmp_path):
    class Boom(FakeEngine):
        def read(self, image, profile, page):
            raise RuntimeError("tesseract crashed")
    r = extract_document(scan_pdf(tmp_path, FIRST["S01_CLEAN"]), engine=Boom([], [0.9]), validator=VALIDATOR)
    assert r.status == "needs_manual_entry" and r.reason == "UNREADABLE_SCAN" and all("error" in a for a in r.attempts)


# ---- real Tesseract (skipped when not installed) -----------------------------------------
REAL = TesseractEngine().available()


@pytest.mark.skipif(not REAL, reason="Tesseract not installed")
def test_real_tesseract_reads_clean_synthetic_scan(tmp_path):
    inv = FIRST["S01_CLEAN"]
    r = extract_document(scan_pdf(tmp_path, inv), validator=VALIDATOR)
    assert r.status == "ok" and r.document_kind == "scanned_good" and r.mean_confidence > 0.7
    assert r.data["invoice_number"] == inv["invoice_number"] and r.data["grand_total"] == inv["grand_total"]


@pytest.mark.skipif(not REAL, reason="Tesseract not installed")
def test_real_tesseract_flags_unreadable_scan(tmp_path):
    r = extract_document(scan_pdf(tmp_path, FIRST["S01_CLEAN"], "unreadable"), validator=VALIDATOR)
    assert r.status == "needs_manual_entry" and "DOC_UNREADABLE" in [f.rule_id for f in r.findings]
