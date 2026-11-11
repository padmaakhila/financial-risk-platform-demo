"""ORM -> plain dict views (keeps routers short and keeps field masking in one place)."""
from __future__ import annotations

from sqlalchemy import select

from backend.core.errors import NotFound
from backend.auth.permissions import can, mask_account
from backend.models import (AiOutput, Document, ExceptionRecord, ExtractedField, IntegrationRecord, Invoice, Review, User, Vendor,
                            WorkflowCheckpoint)


def invoice_row(inv: Invoice, vendor_name: str | None = None) -> dict:
    return {"id": inv.id, "seq": inv.seq, "invoice_number": inv.invoice_number, "vendor_id": inv.vendor_id, "vendor": vendor_name or inv.vendor_name_raw,
            "invoice_date": inv.invoice_date, "due_date": inv.due_date, "po_number": inv.po_number, "grn_number": inv.grn_number,
            "currency": inv.currency, "grand_total": inv.grand_total, "status": inv.status, "document_kind": inv.document_kind}


def exception_view(e: ExceptionRecord) -> dict:
    ev = dict(e.source_evidence or {})
    return {"id": e.id, "invoice_id": e.invoice_id, "type": e.exception_type, "severity": e.severity, "rule_id": e.rule_id, "expected": e.expected_value,
            "actual": e.actual_value, "difference": e.difference, "message": ev.pop("message", None), "outcome": ev.pop("outcome", None),
            "evidence": ev, "status": e.status, "created_at": e.created_at}


def invoice_detail(db, inv_id: int, role: str) -> dict:
    inv = db.get(Invoice, inv_id)
    if inv is None:
        raise NotFound(f"invoice {inv_id} not found")
    vendor = db.get(Vendor, inv.vendor_id) if inv.vendor_id else None
    full_bank = can(role, "view_bank_details")
    header = {**invoice_row(inv, vendor.name if vendor else None), "subtotal": inv.subtotal, "tax_total": inv.tax_total, "notes": inv.notes,
              "vendor_tax_id": inv.vendor_tax_id_raw, "bank_account": inv.bank_account_raw if full_bank else mask_account(inv.bank_account_raw),
              "data_source": inv.data_source, "document_id": inv.document_id, "version": inv.version, "created_at": inv.created_at}
    lines = [{"line_no": l.line_no, "description": l.description, "quantity": l.quantity, "unit_price": l.unit_price, "discount_pct": l.discount_pct,
              "tax_rate": l.tax_rate, "line_total": l.line_total, "tax_amount": l.tax_amount} for l in inv.lines]
    exceptions = [exception_view(e) for e in db.scalars(select(ExceptionRecord).where(ExceptionRecord.invoice_id == inv_id).order_by(ExceptionRecord.id))]
    fields = [{"name": f.field_name, "value": f.value_text, "confidence": f.confidence, "method": f.confidence_method, "page": f.page_number,
               "snippet": f.source_snippet, "bbox": f.bbox} for f in db.scalars(select(ExtractedField).where(ExtractedField.invoice_id == inv_id).order_by(ExtractedField.id))]
    ai = {}
    for kind in ("risk_explanation", "audit_summary"):
        o = db.scalar(select(AiOutput).where(AiOutput.invoice_id == inv_id, AiOutput.kind == kind).order_by(AiOutput.id.desc()).limit(1))
        if o:
            ai[kind] = {"source": o.source, "summary": o.summary, "items": o.items, "caveats": o.caveats, "verification": o.verification, "created_at": o.created_at}
    reviews = [{"id": r.id, "decision": r.decision, "comment": r.comment, "reviewer": name, "created_at": r.created_at}
               for r, name in db.execute(select(Review, User.username).join(User, User.id == Review.reviewer_id).where(Review.invoice_id == inv_id).order_by(Review.id))]
    cp = db.scalar(select(WorkflowCheckpoint).where(WorkflowCheckpoint.invoice_id == inv_id).order_by(WorkflowCheckpoint.id.desc()).limit(1))
    checkpoints = [{"node": c.node, "retry_count": c.retry_count, "at": c.created_at}
                   for c in db.scalars(select(WorkflowCheckpoint).where(WorkflowCheckpoint.invoice_id == inv_id).order_by(WorkflowCheckpoint.id))]
    integrations = [{"integration": i.integration, "status": i.status, "attempts": i.attempts, "at": i.updated_at,
                     "payment_id": (i.response_payload or {}).get("payment_id")} for i in db.scalars(select(IntegrationRecord).where(IntegrationRecord.invoice_id == inv_id).order_by(IntegrationRecord.id))]
    doc = db.get(Document, inv.document_id) if inv.document_id else None
    return {"invoice": header, "lines": lines, "exceptions": exceptions, "extracted_fields": fields, "ai": ai, "reviews": reviews,
            "workflow": {"last_node": cp.node if cp else None, "checkpoints": checkpoints}, "integrations": integrations,
            "document": {"id": doc.id, "filename": doc.original_filename, "mime_type": doc.mime_type, "kind": doc.document_kind} if doc else None}


def vendor_view(v: Vendor, role: str) -> dict:
    full = can(role, "view_bank_details")
    return {"id": v.id, "vendor_code": v.vendor_code, "name": v.name, "tax_id": v.tax_id, "bank_name": v.bank_name,
            "bank_account": v.bank_account if full else mask_account(v.bank_account), "verification_status": v.verification_status, "active": v.active}
