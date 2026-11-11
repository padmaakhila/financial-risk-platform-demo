import pytest

from backend.services.classifier import classify, classify_by_rules, make_plan, train_model
from backend.services.doc_text import grn_lines_text, invoice_lines_text, po_lines_text, vendor_lines_text
from scripts.generate_data import build_dataset

DS = build_dataset(42)
SAMPLES = ([("invoice", "\n".join(invoice_lines_text(i))) for i in DS["invoices"][:80]]
           + [("purchase_order", "\n".join(po_lines_text(p))) for p in DS["purchase_orders"][:80]]
           + [("goods_receipt", "\n".join(grn_lines_text(g))) for g in DS["goods_receipts"][:80]]
           + [("vendor_record", "\n".join(vendor_lines_text(v))) for v in DS["vendors"]])


def test_rules_classify_all_four_document_types():
    wrong = [(label, classify_by_rules(text)[0]) for label, text in SAMPLES if classify_by_rules(text)[0] != label]
    assert not wrong, wrong[:5]


def test_rules_return_unknown_for_unrelated_text():
    assert classify_by_rules("hello world, see you at lunch")[0] == "unknown"
    assert classify("", model=None)["label"] == "unknown"


def test_classify_falls_back_to_rules_without_model():
    r = classify(SAMPLES[0][1], model=None)
    assert r["label"] == "invoice" and r["method"] == "rules"


def test_sklearn_model_accuracy_on_held_out_seed():
    pytest.importorskip("sklearn")
    model = train_model(seed=7)
    held_out = build_dataset(99)
    cases = ([("invoice", "\n".join(invoice_lines_text(i))) for i in held_out["invoices"][:60]]
             + [("purchase_order", "\n".join(po_lines_text(p))) for p in held_out["purchase_orders"][:60]]
             + [("goods_receipt", "\n".join(grn_lines_text(g))) for g in held_out["goods_receipts"][:60]]
             + [("vendor_record", "\n".join(vendor_lines_text(v))) for v in held_out["vendors"]])
    correct = sum(classify(t, model=model)["label"] == y for y, t in cases)
    assert correct / len(cases) >= 0.97


def test_plan_depends_on_type_scan_and_available_records():
    inv = make_plan("invoice", True, has_po=True, has_grn=False)
    assert "ocr" in inv and "two_way_match" in inv and "flag_missing_grn" in inv and inv[-2:] == ["human_review", "audit_summary"]
    assert "read_text_layer" in make_plan("purchase_order", False, False, False)
    assert make_plan("unknown", False, False, False)[-1] == "manual_classification"
