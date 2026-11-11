"""Persist extraction results: documents, extracted fields, invoices, POs/GRNs/vendors, audit events."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.models import (Document, ExceptionRecord, ExtractedField, GoodsReceipt, GoodsReceiptLine, Invoice, InvoiceLine, PurchaseOrder,
                            PurchaseOrderLine, Vendor)
from backend.services.audit import append_audit_event
from backend.services.duplicates import normalize_vendor
from backend.services.extraction import ExtractionResult
from backend.services.upload_validation import ValidatedUpload


def register_document(session: Session, v: ValidatedUpload, uploaded_by: int | None) -> Document:
    doc = Document(original_filename=v.original_filename, stored_filename=v.stored_filename, mime_type=v.mime_type,
                   size_bytes=v.size_bytes, sha256=v.sha256, uploaded_by=uploaded_by, status="UPLOADED")
    session.add(doc)
    session.flush()
    append_audit_event(session, actor_id=uploaded_by, actor_label=f"user:{uploaded_by}", action="DOCUMENT_UPLOADED",
                       entity_type="document", entity_id=doc.id, tool_result={"sha256": v.sha256, "size": v.size_bytes})
    return doc


def resolve_vendor(session: Session, tax_id: str | None, name: str | None) -> Vendor | None:
    """Match by exact tax id, else by exact normalised name. No fuzzy guessing at this stage."""
    if tax_id:
        v = session.scalar(select(Vendor).where(Vendor.tax_id == tax_id))
        if v:
            return v
    if name:
        wanted = normalize_vendor(name)
        for v in session.scalars(select(Vendor)):
            if normalize_vendor(v.name) == wanted:
                return v
    return None


def _store_fields(session: Session, doc: Document, invoice_id: int | None, result: ExtractionResult) -> None:
    for f in result.fields:
        session.add(ExtractedField(document_id=doc.id, invoice_id=invoice_id, field_name=f.name, value_text=f.value_text,
                                   confidence=f.confidence, confidence_method=f.method, page_number=f.page, source_snippet=f.snippet,
                                   bbox={"x0": f.bbox[0], "y0": f.bbox[1], "x1": f.bbox[2], "y1": f.bbox[3]} if f.bbox else None))


def save_extraction(session: Session, doc: Document, result: ExtractionResult, actor_id: int | None = None) -> dict:
    """Store what was extracted. Returns {'status', 'invoice_id' | 'record'}. Never marks a failure as success."""
    doc.doc_type, doc.document_kind = result.doc_type, result.document_kind
    out: dict = {"status": result.status, "reason": result.reason}
    label = "system:extraction_agent"
    if result.doc_type == "invoice" or result.status != "ok":
        d = result.data or {}
        seq = (session.scalar(select(func.max(Invoice.seq))) or 0) + 1
        vendor = resolve_vendor(session, d.get("vendor_tax_id_raw"), d.get("vendor_name_raw"))
        inv = Invoice(seq=seq, vendor_id=vendor.id if vendor else None, document_id=doc.id, data_source="extracted",
                      document_kind=result.document_kind, status="RECEIVED" if result.status == "ok" else "NEEDS_MANUAL_ENTRY",
                      **{k: d.get(k) for k in ("invoice_number", "vendor_name_raw", "vendor_tax_id_raw", "bank_account_raw", "invoice_date",
                                               "due_date", "po_number", "grn_number", "currency", "subtotal", "tax_total", "grand_total", "notes")})
        if result.status == "ok":
            inv.lines = [InvoiceLine(**ln) for ln in d.get("lines", [])]
        session.add(inv)
        session.flush()
        _store_fields(session, doc, inv.id, result)
        for f in result.findings:  # DOC_LOW_CONF / DOC_UNREADABLE become visible exceptions
            session.add(ExceptionRecord(invoice_id=inv.id, exception_type=f.exception_type, severity=f.severity, rule_id=f.rule_id,
                                        expected_value=f.expected, actual_value=f.actual, difference=f.difference,
                                        source_evidence={**f.evidence, "message": f.message, "outcome": f.outcome}, status="OPEN"))
        out["invoice_id"] = inv.id
        doc.status = "EXTRACTED" if result.status == "ok" else "NEEDS_MANUAL_ENTRY"
        entity = ("invoice", inv.id)
    else:
        record = import_record(session, result.doc_type, result.data or {})
        _store_fields(session, doc, None, result)
        out["record"] = record
        doc.status = "EXTRACTED"
        entity = ("document", doc.id)
    append_audit_event(session, actor_id=actor_id, actor_label=label, action="EXTRACTION_COMPLETED", entity_type=entity[0],
                       entity_id=entity[1], tool_result={"status": result.status, "reason": result.reason, "doc_type": result.doc_type,
                                                         "document_kind": result.document_kind, "mean_confidence": result.mean_confidence,
                                                         "attempts": result.attempts, "findings": [f.rule_id for f in result.findings]})
    return out


def import_record(session: Session, doc_type: str, d: dict) -> dict:
    """Create a PO, GRN or vendor from validated data. Existing numbers are rejected, never overwritten."""
    if doc_type == "purchase_order":
        if session.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == d["po_number"])):
            raise ValueError(f"PO {d['po_number']} already exists")
        vendor = session.scalar(select(Vendor).where(Vendor.vendor_code == d["vendor_code"]))
        if vendor is None:
            raise ValueError(f"Unknown vendor code {d['vendor_code']}")
        session.add(PurchaseOrder(po_number=d["po_number"], vendor_id=vendor.id, order_date=d["order_date"], currency=d["currency"],
                                  lines=[PurchaseOrderLine(**ln) for ln in d["lines"]]))
        return {"type": "purchase_order", "number": d["po_number"]}
    if doc_type == "goods_receipt":
        po = session.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == d["po_number"]))
        if po is None:
            raise ValueError(f"GRN refers to unknown PO {d['po_number']}")
        if session.scalar(select(GoodsReceipt).where(GoodsReceipt.grn_number == d["grn_number"])):
            raise ValueError(f"GRN {d['grn_number']} already exists")
        session.add(GoodsReceipt(grn_number=d["grn_number"], po_id=po.id, receipt_date=d["receipt_date"],
                                 lines=[GoodsReceiptLine(**ln) for ln in d["lines"]]))
        return {"type": "goods_receipt", "number": d["grn_number"]}
    if doc_type == "vendor_record":
        if session.scalar(select(Vendor).where(Vendor.vendor_code == d["vendor_code"])):
            raise ValueError(f"Vendor {d['vendor_code']} already exists")
        session.add(Vendor(vendor_code=d["vendor_code"], name=d["name"], tax_id=d.get("tax_id"), bank_account=d.get("bank_account"),
                           bank_name=d.get("bank_name"), verification_status="UNVERIFIED"))
        return {"type": "vendor_record", "number": d["vendor_code"]}
    raise ValueError(f"cannot import document type {doc_type}")
