import re
from collections import Counter
from decimal import Decimal

from backend.core.constants import BANK_ACCOUNT_REGEX, TAX_ID_REGEX
from scripts.generate_data import SCENARIOS, build_dataset, money

DS = build_dataset(42)
BY_CODE = {}
for inv in DS["invoices"]:
    BY_CODE.setdefault(inv["scenario_code"], []).append(inv)
TRUTH = {t["invoice_seq"]: t for t in DS["ground_truth"] if t["invoice_seq"]}


def arithmetic_rules(inv) -> set:
    """Independent re-implementation used only to validate the generator's ground truth."""
    found = set()
    for ln in inv["lines"]:
        if ln["line_total"] != money(ln["quantity"] * ln["unit_price"] * (100 - ln["discount_pct"]) / 100):
            found.add("ARITH_LINE_TOTAL")
        if ln["tax_amount"] != money(ln["line_total"] * ln["tax_rate"]):
            found.add("ARITH_TAX")
    if inv["subtotal"] != money(sum(l["line_total"] for l in inv["lines"])):
        found.add("ARITH_SUBTOTAL")
    if inv["tax_total"] != money(sum(l["tax_amount"] for l in inv["lines"])):
        found.add("ARITH_TAX")
    if inv["grand_total"] != money(inv["subtotal"] + inv["tax_total"]):
        found.add("ARITH_GRAND_TOTAL")
    return found


def test_at_least_500_invoices_and_linked_records():
    assert len(DS["invoices"]) >= 500
    assert len(DS["purchase_orders"]) > 400 and len(DS["goods_receipts"]) > 400
    codes = {v["vendor_code"] for v in DS["vendors"]}
    assert all(i["vendor_code"] in codes for i in DS["invoices"])


def test_dataset_is_reproducible_and_seed_sensitive():
    assert build_dataset(42) == DS
    assert build_dataset(7) != DS


def test_all_24_scenarios_have_ground_truth():
    expected = {code for code, _, _ in SCENARIOS}
    assert len(expected) == 24
    assert {t["scenario_code"] for t in DS["ground_truth"]} == expected


def test_money_is_always_decimal_with_two_places():
    for inv in DS["invoices"]:
        for key in ("subtotal", "tax_total", "grand_total"):
            assert isinstance(inv[key], Decimal) and inv[key] == inv[key].quantize(Decimal("0.01"))
        for ln in inv["lines"]:
            assert isinstance(ln["unit_price"], Decimal) and isinstance(ln["line_total"], Decimal)


def test_ground_truth_arithmetic_rules_match_actual_data():
    for inv in DS["invoices"]:
        expected = set(TRUTH[inv["seq"]]["expected"]["rules"]) & {"ARITH_LINE_TOTAL", "ARITH_TAX", "ARITH_SUBTOTAL", "ARITH_GRAND_TOTAL"}
        assert arithmetic_rules(inv) == expected, (inv["invoice_number"], inv["scenario_code"])


def test_clean_invoice_has_matching_po_and_grn():
    pos = {p["po_number"]: p for p in DS["purchase_orders"]}
    grns = {g["grn_number"]: g for g in DS["goods_receipts"]}
    for inv in BY_CODE["S01_CLEAN"]:
        po, grn = pos[inv["po_number"]], grns[inv["grn_number"]]
        for il, pl, gl in zip(inv["lines"], po["lines"], grn["lines"]):
            assert il["unit_price"] == pl["unit_price"] and il["quantity"] == pl["quantity"] == gl["quantity_received"]


def test_missing_po_and_grn_scenarios():
    pos = {p["po_number"] for p in DS["purchase_orders"]}
    grns = {g["grn_number"] for g in DS["goods_receipts"]}
    assert all(i["po_number"] not in pos for i in BY_CODE["S10_MISSING_PO"])
    assert all(i["grn_number"] not in grns for i in BY_CODE["S11_MISSING_GRN"])
    assert all(i["po_number"] in pos for i in BY_CODE["S11_MISSING_GRN"])


def test_quantity_scenarios_against_po_and_grn():
    pos = {p["po_number"]: p for p in DS["purchase_orders"]}
    grns = {g["grn_number"]: g for g in DS["goods_receipts"]}
    for inv in BY_CODE["S08_QTY_GT_PO"]:
        assert any(il["quantity"] > pl["quantity"] for il, pl in zip(inv["lines"], pos[inv["po_number"]]["lines"]))
    for inv in BY_CODE["S09_QTY_GT_GRN"]:
        po, grn = pos[inv["po_number"]], grns[inv["grn_number"]]
        assert all(il["quantity"] <= pl["quantity"] for il, pl in zip(inv["lines"], po["lines"]))
        assert any(il["quantity"] > gl["quantity_received"] for il, gl in zip(inv["lines"], grn["lines"]))
    for inv in BY_CODE["S12_PARTIAL_GRN"]:
        po, grn = pos[inv["po_number"]], grns[inv["grn_number"]]
        assert all(il["quantity"] == gl["quantity_received"] < pl["quantity"]
                   for il, pl, gl in zip(inv["lines"], po["lines"], grn["lines"]))


def test_price_difference_exceeds_default_tolerance():
    pos = {p["po_number"]: p for p in DS["purchase_orders"]}
    for inv in BY_CODE["S07_PRICE_DIFF"]:
        diffs = [abs(il["unit_price"] - pl["unit_price"]) / pl["unit_price"] for il, pl in zip(inv["lines"], pos[inv["po_number"]]["lines"])]
        assert max(diffs) > Decimal("0.01")


def test_identifier_format_scenarios():
    assert all(re.match(TAX_ID_REGEX, i["vendor_tax_id_raw"]) for i in BY_CODE["S01_CLEAN"])
    assert all(re.match(BANK_ACCOUNT_REGEX, i["bank_account_raw"]) for i in BY_CODE["S01_CLEAN"])
    assert not any(re.match(TAX_ID_REGEX, i["vendor_tax_id_raw"]) for i in BY_CODE["S13_BAD_TAX_ID"])
    assert not any(re.match(BANK_ACCOUNT_REGEX, i["bank_account_raw"]) for i in BY_CODE["S14_BAD_BANK"])


def test_missing_fields_prompt_injection_and_document_kinds():
    assert all(i["invoice_date"] is None and i["currency"] is None for i in BY_CODE["S15_MISSING_FIELDS"])
    assert all("ignore" in i["notes"].lower() or "system:" in i["notes"].lower() or "disregard" in i["notes"].lower()
              for i in BY_CODE["S19_PROMPT_INJECTION"])
    assert {i["document_kind"] for i in BY_CODE["S16_UNREADABLE_SCAN"]} == {"scanned_unreadable"}
    assert {i["document_kind"] for i in BY_CODE["S17_LOW_CONF_OCR"]} == {"scanned_low_quality"}


def test_duplicates_are_later_than_originals_and_differ_as_designed():
    by_seq = {i["seq"]: i for i in DS["invoices"]}
    for code in ("S02_DUP_EXACT", "S03_DUP_FUZZY"):
        for dup in BY_CODE[code]:
            orig = by_seq[TRUTH[dup["seq"]]["expected"]["duplicate_of_seq"]]
            assert dup["seq"] > orig["seq"] and dup["vendor_code"] == orig["vendor_code"]
            assert dup["grand_total"] == orig["grand_total"]
            same_number = dup["invoice_number"].strip().casefold() == orig["invoice_number"].strip().casefold()
            assert same_number == (code == "S02_DUP_EXACT")
    assert all(d["vendor_name_raw"] != by_seq[TRUTH[d["seq"]]["expected"]["duplicate_of_seq"]]["vendor_name_raw"]
               for d in BY_CODE["S03_DUP_FUZZY"])


def test_unique_invoice_numbers_except_exact_duplicates():
    counts = Counter(i["invoice_number"] for i in DS["invoices"])
    dup_numbers = {i["invoice_number"] for i in BY_CODE["S02_DUP_EXACT"]}
    assert {n for n, c in counts.items() if c > 1} == dup_numbers


def test_no_invoice_uses_blocked_vendors():
    blocked = {v["vendor_code"] for v in DS["vendors"] if not v["active"]}
    assert blocked and not any(i["vendor_code"] in blocked for i in DS["invoices"])
