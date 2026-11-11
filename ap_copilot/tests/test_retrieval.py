from ap_copilot import config
from ap_copilot.answer_service import answer
from ap_copilot.retrieval import build_context, detect_intents, extract_identifiers
from .conftest import FakeRepo, ScriptedLLM, sample_data


def run(repo, scope, q, hint=None, llm=None):
    ctx = build_context(repo, scope, q, hint)
    return ctx, answer(q, ctx, scope, None, 30, llm_call=llm or ScriptedLLM(exc=RuntimeError("x")))


def test_identifier_extraction_and_hint():
    assert extract_identifiers("Why was invoice INV-2026-00085 rejected vs PO-12?") == ["INV-2026-00085", "PO-12"]
    assert extract_identifiers("this invoice", hint="INV-9")[0] == "INV-9"
    assert len(extract_identifiers(" ".join("AB-%d" % i for i in range(50)))) == config.MAX_IDENTIFIERS


def test_existing_invoice(repo, scopes):
    ctx, res = run(repo, scopes["admin"], "Why was invoice INV-2026-00085 rejected?")
    assert ctx["invoices"][0]["status"] == "REJECTED"
    assert "INV-2026-00085" in res["answer"] and "MATCH_MISSING_PO" in res["answer"] and res["invoice"]["invoice_number"] == "INV-2026-00085"
    assert any(e["ref"] == "EXC:INV-2026-00085#1" for e in res["evidence"])


def test_missing_invoice_reports_not_found_without_llm(repo, scopes):
    llm = ScriptedLLM(reply="x")
    ctx, res = run(repo, scopes["admin"], "Why was INV-0000-00000 rejected?", llm=llm)
    assert res["mode"] == "not_found" and "INV-0000-00000" in res["answer"] and "Not found" in res["answer"] and llm.prompts == []


def test_no_identifier_asks_for_one(repo, scopes):
    _, res = run(repo, scopes["admin"], "Why was it rejected?")
    assert res["mode"] == "not_found" and "invoice number" in res["answer"]


def test_vendor_lookup(repo, scopes):
    _, res = run(repo, scopes["admin"], "Is vendor VEN-001 verified?")
    assert "unverified" in res["answer"] and "VEN-001" in res["answer"]


def test_po_lookup_and_grn_lookup(repo, scopes):
    _, res = run(repo, scopes["admin"], "Show PO-1234")
    assert "PO-1234" in res["answer"] and "1 line" in res["answer"]
    _, res = run(repo, scopes["admin"], "Explain GRN-5555")
    assert "GRN-5555" in res["answer"] and "PO-1234" in res["answer"]


def test_missing_extraction_field_and_low_confidence(repo, scopes):
    ctx, res = run(repo, scopes["admin"], "Show the missing extraction fields for INV-2026-00085")
    f = {x["field_name"]: x for x in ctx["invoices"][0]["fields"]}
    assert f["tax_total"]["missing"] and f["po_number"]["low_confidence"] and not f["bank_account"]["low_confidence"]
    assert "MISSING" in res["answer"] and "not proof" in res["answer"] and "tax_total" in res["answer"]


def test_existing_and_missing_risk_findings(repo, data, scopes):
    _, res = run(repo, scopes["admin"], "Summarize risk findings of INV-2026-00085")
    assert "severity high" in res["answer"] and "R-PO-001" in res["answer"]
    data["exceptions"] = {}
    _, res2 = run(FakeRepo(**data), scopes["admin"], "Summarize risk findings of INV-2026-00085")
    assert "does not prove the invoice is correct" in res2["answer"]


def test_unverified_po_reference_is_not_reported_as_matched(repo, scopes):
    ctx, res = run(repo, scopes["admin"], "Why did the PO matching fail for INV-2026-00085?")
    m = ctx["invoices"][0]["match"]
    assert m["po_reference_stored_on_invoice"] == "PO-9999" and m["po_reference_from_extraction"] == "PO-9999"
    assert m["po_master_record_found"] is False and not any("matched" in k for k in m)
    assert "PO master record found: **no**" in res["answer"] and "does not by itself mean" in res["answer"]
    assert "purchase order master" in res["answer"]


def test_grn_reference_missing_vs_found(data, scopes):
    data["invoices"][0].update(po_number="PO-1234", grn_number="GRN-0001")
    ctx = build_context(FakeRepo(**data), scopes["admin"], "INV-2026-00085")
    m = ctx["invoices"][0]["match"]
    assert m["po_master_record_found"] is True and m["grn_master_record_found"] is False
    data["invoices"][0]["grn_number"] = "GRN-5555"
    m = build_context(FakeRepo(**data), scopes["admin"], "INV-2026-00085")["invoices"][0]["match"]
    assert m["grn_master_record_found"] is True and m["grn_belongs_to_found_po"] is True


def test_po_vendor_mismatch_flagged(data, scopes):
    data["invoices"][0]["po_number"] = "PO-1234"
    data["pos"][0]["vendor_id"] = 99
    m = build_context(FakeRepo(**data), scopes["admin"], "INV-2026-00085")["invoices"][0]["match"]
    assert m["po_vendor_same_as_invoice_vendor"] is False


def test_pending_listing_and_high_risk_listing(data, scopes):
    data["invoices"][0]["status"] = "PENDING_REVIEW"
    r = FakeRepo(**data)
    ctx, res = run(r, scopes["admin"], "Show invoices pending review")
    assert ctx["listing"] and "INV-2026-00085" in res["answer"]
    ctx, res = run(FakeRepo(**data), scopes["admin"], "What are the high-risk findings?")
    assert ctx["high_risk"] and "R-PO-001" in res["answer"]


def test_retrieval_is_bounded(data, scopes):
    base = data["invoices"][0]
    data["invoices"] = [dict(base, id=i, invoice_number="INV-9-%05d" % i) for i in range(100)]
    ids = " ".join("INV-9-%05d" % i for i in range(100))
    r = FakeRepo(**data)
    ctx = build_context(r, scopes["admin"], ids)
    assert len(ctx["invoices"]) <= config.MAX_INVOICES and r.limit_inv == config.MAX_INVOICES
    assert sum("exceptions" in i for i in ctx["invoices"]) <= config.MAX_DETAIL_INVOICES
    assert len(ctx["tokens"]) <= config.MAX_IDENTIFIERS


def test_intents():
    i = detect_intents("How do I upload? Show pending. Any high risk?")
    assert i["howto"] and i["pending"] and i["high_risk"]


def test_howto_uses_help_text_not_data(repo, scopes):
    llm = ScriptedLLM(reply="Use Document Upload to add invoices.")
    _, res = run(repo, scopes["ap_clerk"], "How do I upload an invoice?", llm=llm)
    assert res["mode"] == "facts+llm" and "Administration" not in llm.prompts[0][1]
    assert repo.calls == [] or "find_invoices" not in repo.calls
