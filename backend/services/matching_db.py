"""Database adapter: load records, run the pure Matching Service, store exceptions + audit event."""
from __future__ import annotations

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from backend.core.errors import NotFound
from backend.models import (ExceptionRecord, GoodsReceipt, Invoice, PurchaseOrder, Setting, Vendor)
from backend.services.audit import append_audit_event
from backend.services.matching import EvaluationResult, evaluate_invoice
from backend.services.rules import Tolerances


def load_tolerances(session: Session) -> Tolerances:
    return Tolerances.from_mapping({s.key: s.value for s in session.scalars(select(Setting))})


def invoice_to_dict(inv: Invoice, vendor: Vendor | None) -> dict:
    return {
        "id": inv.id, "seq": inv.seq, "invoice_number": inv.invoice_number,
        "vendor_code": vendor.vendor_code if vendor else None, "vendor_name_raw": inv.vendor_name_raw,
        "vendor_tax_id_raw": inv.vendor_tax_id_raw, "bank_account_raw": inv.bank_account_raw,
        "invoice_date": inv.invoice_date, "due_date": inv.due_date, "po_number": inv.po_number, "grn_number": inv.grn_number,
        "currency": inv.currency, "subtotal": inv.subtotal, "tax_total": inv.tax_total, "grand_total": inv.grand_total,
        "notes": inv.notes,
        "lines": [{"line_no": l.line_no, "description": l.description, "quantity": l.quantity, "unit_price": l.unit_price,
                   "discount_pct": l.discount_pct, "tax_rate": l.tax_rate, "line_total": l.line_total, "tax_amount": l.tax_amount}
                  for l in inv.lines],
    }


def run_matching_for_invoice(session: Session, invoice_id: int, *, actor_id: int | None = None,
                             actor_label: str = "system:matching_service") -> EvaluationResult:
    """Idempotent: re-running replaces this invoice's OPEN exceptions; resolved/waived ones are kept."""
    inv = session.get(Invoice, invoice_id)
    if inv is None:
        raise NotFound(f"invoice {invoice_id} not found")
    vendor = session.get(Vendor, inv.vendor_id) if inv.vendor_id else None
    po_row = session.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == inv.po_number)) if inv.po_number else None
    grn_row = session.scalar(select(GoodsReceipt).where(GoodsReceipt.grn_number == inv.grn_number)) if inv.grn_number else None
    po = grn = None
    if po_row:
        pv = session.get(Vendor, po_row.vendor_id)
        po = {"po_number": po_row.po_number, "vendor_code": pv.vendor_code if pv else None,
              "lines": [{"line_no": l.line_no, "description": l.description, "quantity": l.quantity,
                         "unit_price": l.unit_price, "tax_rate": l.tax_rate} for l in po_row.lines]}
    if grn_row:
        gpo = session.get(PurchaseOrder, grn_row.po_id)
        grn = {"grn_number": grn_row.grn_number, "po_number": gpo.po_number if gpo else None,
               "lines": [{"po_line_no": l.po_line_no, "quantity_received": l.quantity_received} for l in grn_row.lines]}
    cond = [Invoice.vendor_id == inv.vendor_id] if inv.vendor_id else []
    if inv.grand_total is not None:
        cond.append(Invoice.grand_total == inv.grand_total)
    priors = []
    if cond:
        for o in session.scalars(select(Invoice).where(Invoice.seq < inv.seq, or_(*cond))):
            ov = session.get(Vendor, o.vendor_id) if o.vendor_id else None
            priors.append(invoice_to_dict(o, ov))
    vendor_dict = {"vendor_code": vendor.vendor_code, "bank_account": vendor.bank_account} if vendor else None
    result = evaluate_invoice(invoice_to_dict(inv, vendor), vendor=vendor_dict, po=po, grn=grn, prior_invoices=priors,
                              tolerances=load_tolerances(session))
    session.execute(delete(ExceptionRecord).where(ExceptionRecord.invoice_id == inv.id, ExceptionRecord.status == "OPEN",
                                                  ExceptionRecord.rule_id.notlike("DOC\\_%", escape="\\")))  # DOC_* findings come from extraction; keep them
    for f in result.findings:
        session.add(ExceptionRecord(invoice_id=inv.id, exception_type=f.exception_type, severity=f.severity, rule_id=f.rule_id,
                                    expected_value=f.expected, actual_value=f.actual, difference=f.difference,
                                    source_evidence={**f.evidence, "message": f.message, "outcome": f.outcome}, status="OPEN"))
    append_audit_event(session, actor_id=actor_id, actor_label=actor_label, action="MATCHING_COMPLETED", entity_type="invoice",
                       entity_id=inv.id, tool_result={"result": result.result, "mode": result.match_mode,
                                                       "rules": sorted(result.rule_ids)})
    session.flush()
    return result
