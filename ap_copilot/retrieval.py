"""Bounded, permission-filtered retrieval. This module holds the *logic*; all
database access goes through a ``Repo`` object (see orm_repo.OrmRepo), which
only issues read-only SELECTs. Data a user may not see is never fetched, so it
can never reach the LLM context.

Terminology kept strictly separate (critical matching rule):
  * reference stored on the invoice record      -> inv["po_number"]
  * reference found by the extractor             -> extracted field value
  * master record found in the PO/GRN tables     -> "master_record_found"
  * what the platform's engine concluded          -> exceptions (findings)
This module never states that a PO/GRN is "matched"; it reports these facts.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from . import config
from .guardrails import sanitize_untrusted as su
from .pii import is_bank_field, mask_value
from .security import Scope

_HYPHEN_ID = re.compile(r"\b[A-Za-z]{2,8}(?:[-_/][A-Za-z0-9]+)+\b")
_COMPACT_ID = re.compile(r"\b[A-Za-z]{2,5}\d{3,}\b")
_QUOTED = re.compile(r"[\"“']([^\"”']{3,60})[\"”']")

_INTENTS = {
    "pending": r"\b(pending|awaiting|waiting|in review|to review|review queue|needs? review|open invoices)\b",
    "high_risk": r"\b(high[- ]?risk|critical|severe|high severity)\b",
    "report": r"\b(report|summary of all|overview|how many|count of|statistics|totals?)\b",
    "vendor": r"\b(vendor|supplier|verified|verification|tax id)\b",
    "po": r"\b(po|purchase order|purchase-order)\b",
    "grn": r"\b(grn|goods receipt|goods-receipt|receipt note)\b",
    "extraction": r"\b(extract\w*|ocr|confidence|missing fields?|fields?)\b",
    "audit": r"\b(audit|history|who (?:changed|approved|rejected)|event log)\b",
    "workflow": r"\b(workflow|checkpoint|status|stage|rejected|approved|flagged|why was)\b",
    "howto": r"\b(how do i|how to|how can i|where (?:can|do) i|what does this page)\b",
}
_STATUS_WORDS = {"pending": ["pending", "review"]}


def extract_identifiers(question: str, hint: Optional[str] = None) -> List[str]:
    toks: List[str] = []
    for rx in (_HYPHEN_ID, _COMPACT_ID):
        for t in rx.findall(question or ""):
            if any(c.isdigit() for c in t) and t.upper() not in [x.upper() for x in toks]:
                toks.append(t)
    if hint:
        h = hint.strip()[:100]
        if h and h.upper() not in [x.upper() for x in toks]:
            toks.insert(0, h)
    return toks[:config.MAX_IDENTIFIERS]


def detect_intents(question: str) -> Dict[str, bool]:
    q = (question or "").lower()
    return {k: bool(re.search(v, q)) for k, v in _INTENTS.items()}


def _dec(v: Any) -> Optional[Decimal]:
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None
    return d / 100 if d > 1 else d      # tolerate 0-100 scales


def _empty(v: Any) -> bool:
    return v is None or str(v).strip() == ""


def _same(a: Any, b: Any) -> bool:
    return not _empty(a) and not _empty(b) and str(a).strip().upper() == str(b).strip().upper()


# ---------------------------------------------------------------- builders
class _Evidence:
    def __init__(self):
        self.items: List[Dict[str, str]] = []

    def add(self, kind: str, ref: str, label: str) -> str:
        ref = su(ref, 120)
        self.items.append({"kind": kind, "ref": ref, "label": su(label, 160)})
        return ref


def _inv_public(inv: Dict[str, Any], scope: Scope) -> Dict[str, Any]:
    out = {k: su(inv.get(k), 80) if isinstance(inv.get(k), str) else inv.get(k)
           for k in ("id", "invoice_number", "vendor_id", "invoice_date", "due_date", "po_number", "grn_number",
                     "currency", "subtotal", "tax_total", "grand_total", "status", "document_kind", "document_id",
                     "data_source", "created_at")}
    out["vendor_name_raw"] = su(inv.get("vendor_name_raw"), config.MAX_TEXT_CHARS)
    out["notes"] = su(inv.get("notes"), config.MAX_NOTE_CHARS)
    if scope.bank:
        out["bank_account_raw_masked"] = mask_value(inv.get("bank_account_raw"))
    return out


def match_facts(inv: Dict[str, Any], pos: List[Dict[str, Any]], grns: List[Dict[str, Any]],
                exceptions: List[Dict[str, Any]], fields: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Facts only. Deliberately has no key that says 'matched'."""
    po_ref, grn_ref = inv.get("po_number"), inv.get("grn_number")
    po = next((p for p in pos if _same(p.get("po_number"), po_ref)), None)
    grn = next((g for g in grns if _same(g.get("grn_number"), grn_ref)), None)
    ext_po = next((f.get("value") for f in fields
                   if str(f.get("field_name", "")).lower() in ("po_number", "po", "purchase_order", "purchase_order_number")), None)
    ext_grn = next((f.get("value") for f in fields
                    if str(f.get("field_name", "")).lower() in ("grn_number", "grn", "goods_receipt", "goods_receipt_number")), None)
    facts: Dict[str, Any] = {
        "po_reference_stored_on_invoice": po_ref if not _empty(po_ref) else None,
        "po_reference_from_extraction": ext_po,
        "po_master_record_found": (po is not None) if not _empty(po_ref) else None,
        "po_vendor_same_as_invoice_vendor": None,
        "po_currency_same_as_invoice": None,
        "grn_reference_stored_on_invoice": grn_ref if not _empty(grn_ref) else None,
        "grn_reference_from_extraction": ext_grn,
        "grn_master_record_found": (grn is not None) if not _empty(grn_ref) else None,
        "grn_belongs_to_found_po": None,
        "platform_findings_about_po_grn": [
            {"type": e.get("exception_type"), "rule_id": e.get("rule_id"), "severity": e.get("severity"), "status": e.get("status")}
            for e in exceptions
            if re.search(r"PO|GRN|MATCH|RECEIPT|QUANTITY|PRICE", str(e.get("exception_type", "")) + str(e.get("rule_id", "")), re.I)
        ],
    }
    if po is not None:
        if po.get("vendor_id") is not None and inv.get("vendor_id") is not None:
            facts["po_vendor_same_as_invoice_vendor"] = po["vendor_id"] == inv["vendor_id"]
        if not _empty(po.get("currency")) and not _empty(inv.get("currency")):
            facts["po_currency_same_as_invoice"] = _same(po["currency"], inv["currency"])
    if grn is not None and po is not None and grn.get("po_id") is not None and po.get("id") is not None:
        facts["grn_belongs_to_found_po"] = grn["po_id"] == po["id"]
    return facts


def _fields_view(rows: List[Dict[str, Any]], with_snippets: bool, ev: _Evidence, inv_no: str) -> List[Dict[str, Any]]:
    out = []
    for r in rows[:config.MAX_FIELDS]:
        name = su(r.get("field_name"), 60)
        raw_val = r.get("value_text")
        val = mask_value(raw_val) if is_bank_field(name) else su(raw_val, config.MAX_FIELD_VALUE_CHARS)
        conf = _dec(r.get("confidence"))
        item = {
            "field_name": name, "value": val,
            "confidence": str(conf.quantize(Decimal("0.01"))) if conf is not None else None,
            "confidence_method": su(r.get("confidence_method"), 40),
            "page_number": r.get("page_number"),
            "missing": _empty(raw_val),
            "low_confidence": conf is not None and conf < config.LOW_CONFIDENCE,
        }
        if with_snippets and not _empty(r.get("source_snippet")):
            item["source_snippet"] = su(r.get("source_snippet"), config.MAX_SNIPPET_CHARS)
        item["ref"] = ev.add("extracted_field", "FLD:%s:%s" % (inv_no, name), "Extracted field %s" % name)
        out.append(item)
    return out


def _exc_view(rows, scope: Scope, ev: _Evidence, inv_no: str):
    out = []
    for i, r in enumerate(rows[:config.MAX_EXCEPTIONS], 1):
        item = {
            "exception_type": su(r.get("exception_type"), 60), "severity": su(r.get("severity"), 20),
            "rule_id": su(r.get("rule_id"), 60), "expected_value": su(r.get("expected_value"), 80),
            "actual_value": su(r.get("actual_value"), 80), "difference": su(r.get("difference"), 80),
            "status": su(r.get("status"), 30),
        }
        if scope.evidence and not _empty(r.get("source_evidence")):
            item["source_evidence"] = su(r.get("source_evidence"), config.MAX_SNIPPET_CHARS)
        item["ref"] = ev.add("risk_finding", "EXC:%s#%d" % (inv_no, i), "%s (%s)" % (item["exception_type"], item["rule_id"]))
        out.append(item)
    return out


def build_context(repo, scope: Scope, question: str, invoice_hint: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve a small, permission-filtered, sanitized context. Raises whatever
    the repo raises on DB failure (the caller turns that into 'cannot retrieve')."""
    ev = _Evidence()
    notes: List[str] = []
    intents = detect_intents(question)
    tokens = extract_identifiers(question, invoice_hint)
    quoted = [m for m in _QUOTED.findall(question or "")][:3]

    ctx: Dict[str, Any] = {"tokens": tokens, "intents": intents, "invoices": [], "vendors": [], "pos": [],
                           "grns": [], "listing": [], "high_risk": [], "report": None, "not_found": [], "notes": notes}
    if not scope.records:
        notes.append("This user does not have permission to view platform records.")
        ctx["evidence"], ctx["counts"] = ev.items, {}
        return ctx

    # ---- invoices
    status_terms = _STATUS_WORDS["pending"] if intents["pending"] and not tokens else []
    invoices = []
    if tokens:
        invoices = repo.find_invoices(tokens, [], [], config.MAX_INVOICES)
    elif status_terms:
        ctx["listing"] = [{k: su(v, 80) for k, v in _list_row(i).items()}
                          for i in repo.find_invoices([], [], status_terms, config.MAX_LIST)]
    # ---- vendors (by code / quoted name / vendors of retrieved invoices)
    vendor_ids = sorted({i["vendor_id"] for i in invoices if i.get("vendor_id") is not None})
    vendors = []
    if tokens or quoted or vendor_ids:
        vendors = repo.find_vendors(tokens, quoted, vendor_ids, config.MAX_VENDORS, scope.bank)
    # ---- PO / GRN master records
    po_numbers = tokens + [i["po_number"] for i in invoices if not _empty(i.get("po_number"))]
    grn_numbers = tokens + [i["grn_number"] for i in invoices if not _empty(i.get("grn_number"))]
    pos = repo.find_pos(po_numbers, config.MAX_POS) if po_numbers else []
    grns = repo.find_grns(grn_numbers, config.MAX_GRNS) if grn_numbers else []

    # ---- per-invoice detail
    for idx, inv in enumerate(invoices):
        pub = _inv_public(inv, scope)
        inv_no = pub["invoice_number"] or str(pub["id"])
        pub["ref"] = ev.add("invoice", "INV:%s" % inv_no, "Invoice %s" % inv_no)
        if idx < config.MAX_DETAIL_INVOICES:
            excs = repo.exceptions(inv["id"], config.MAX_EXCEPTIONS)
            pub["exceptions"] = _exc_view(excs, scope, ev, inv_no)
            fields_view: List[Dict[str, Any]] = []
            pub["fields_status"] = "withheld_permission"
            if scope.evidence:
                doc_id = inv.get("document_id")
                owned = True
                if scope.role == "ap_clerk" and doc_id is not None:      # preserve clerk ownership rule
                    owned = repo.document_visible(doc_id) is True
                if owned:
                    rows = repo.extracted_fields(inv["id"], True, config.MAX_FIELDS)
                    fields_view = _fields_view(rows, True, ev, inv_no)
                    pub["fields_status"] = "ok" if fields_view else "no_records"
                else:
                    pub["fields_status"] = "withheld_ownership"
                    notes.append("Extraction evidence for %s belongs to another user's document and is not shown." % inv_no)
            else:
                notes.append("Extraction evidence requires evidence permission and was not retrieved.")
            pub["fields"] = fields_view
            pub["missing_header_fields"] = [h for h in config.HEADER_FIELDS if _empty(inv.get(h))]
            pub["match"] = match_facts(inv, pos, grns, excs, fields_view)
            if scope.queue or scope.audit:
                pub["reviews"] = [{"decision": su(r.get("decision"), 30), "comment": su(r.get("comment"), config.MAX_NOTE_CHARS),
                                   "created_at": r.get("created_at")} for r in repo.reviews(inv["id"], config.MAX_REVIEWS)]
            else:
                pub["reviews"] = None
            pub["checkpoints"] = [{k: su(v, 60) for k, v in c.items()} for c in repo.checkpoints(inv["id"], config.MAX_CHECKPOINTS)]
            if scope.audit:
                pub["audit"] = []
                for j, a in enumerate(repo.audit_events(inv["id"], config.MAX_AUDIT), 1):
                    pub["audit"].append({"action": su(a.get("action"), 60), "actor": su(a.get("actor_label"), 60),
                                         "decision": su(a.get("decision"), 30), "created_at": a.get("created_at"),
                                         "ref": ev.add("audit", "AUD:%s#%d" % (inv_no, j), "Audit event %s" % su(a.get("action"), 40))})
            else:
                pub["audit"] = None
                if intents["audit"]:
                    notes.append("Audit history requires audit permission and was not retrieved.")
        ctx["invoices"].append(pub)

    # ---- vendors / POs / GRNs views
    for v in vendors:
        item = {"vendor_code": su(v.get("vendor_code"), 40), "name": su(v.get("name"), config.MAX_TEXT_CHARS),
                "verification_status": su(v.get("verification_status"), 30), "active": v.get("active"),
                "tax_id": su(v.get("tax_id"), 40)}
        if scope.bank:
            item["bank_account_masked"] = mask_value(v.get("bank_account"))
        item["ref"] = ev.add("vendor", "VEN:%s" % item["vendor_code"], "Vendor %s" % item["name"])
        ctx["vendors"].append(item)
    for p in pos:
        ctx["pos"].append({"id": p.get("id"), "po_number": su(p.get("po_number"), 60), "vendor_id": p.get("vendor_id"),
                           "order_date": p.get("order_date"), "currency": su(p.get("currency"), 10), "status": su(p.get("status"), 30),
                           "lines": [{k: su(v, 80) for k, v in l.items()} for l in (p.get("lines") or [])[:config.MAX_LINES]],
                           "ref": ev.add("purchase_order", "PO:%s" % su(p.get("po_number"), 60), "PO %s" % su(p.get("po_number"), 60))})
    for g in grns:
        ctx["grns"].append({"id": g.get("id"), "grn_number": su(g.get("grn_number"), 60), "po_id": g.get("po_id"),
                            "po_number": su(g.get("po_number"), 60), "receipt_date": g.get("receipt_date"),
                            "lines": [{k: su(v, 80) for k, v in l.items()} for l in (g.get("lines") or [])[:config.MAX_LINES]],
                            "ref": ev.add("goods_receipt", "GRN:%s" % su(g.get("grn_number"), 60), "GRN %s" % su(g.get("grn_number"), 60))})

    # ---- high-risk listing (no identifier needed)
    if intents["high_risk"] and not tokens:
        for r in repo.open_high_risk(config.MAX_LIST):
            ctx["high_risk"].append({"invoice_number": su(r.get("invoice_number"), 60), "exception_type": su(r.get("exception_type"), 60),
                                     "severity": su(r.get("severity"), 20), "rule_id": su(r.get("rule_id"), 60),
                                     "status": su(r.get("status"), 30)})
    # ---- reports (view_reports only)
    if intents["report"]:
        if scope.reports:
            ctx["report"] = repo.report_counts()
        else:
            notes.append("Reports require report permission and were not retrieved.")

    # ---- identifiers that matched nothing (query succeeded => genuinely not found)
    known = {str(x.get("invoice_number", "")).upper() for x in ctx["invoices"]}
    known |= {str(x.get("po_number", "")).upper() for x in ctx["pos"]} | {str(x.get("grn_number", "")).upper() for x in ctx["grns"]}
    known |= {str(x.get("vendor_code", "")).upper() for x in ctx["vendors"]}
    known |= {str(i.get("po_number", "")).upper() for i in ctx["invoices"]} | {str(i.get("grn_number", "")).upper() for i in ctx["invoices"]}
    ctx["not_found"] = [t for t in tokens if t.upper() not in known]
    ctx["evidence"] = ev.items
    ctx["counts"] = {"invoices": len(ctx["invoices"]), "vendors": len(ctx["vendors"]), "pos": len(ctx["pos"]),
                     "grns": len(ctx["grns"]), "listing": len(ctx["listing"]), "high_risk": len(ctx["high_risk"]),
                     "evidence": len(ev.items)}
    return ctx


def _list_row(i: Dict[str, Any]) -> Dict[str, Any]:
    return {k: i.get(k) for k in ("invoice_number", "vendor_name_raw", "status", "grand_total", "currency", "invoice_date")}


def has_data(ctx: Dict[str, Any]) -> bool:
    return any(ctx.get(k) for k in ("invoices", "vendors", "pos", "grns", "listing", "high_risk", "report"))
