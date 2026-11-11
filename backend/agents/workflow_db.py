"""Database implementations of the allowlisted workflow tools (one short transaction per tool call)."""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select, update

from backend.core.errors import NotFound
from backend.database.session import session_scope
from backend.integrations.clients import IntegrationUnavailable
from backend.models import (AiOutput, AuditEvent, ExceptionRecord, GoodsReceipt, IntegrationRecord, Invoice, LlmUsage, PurchaseOrder,
                            Vendor, WorkflowCheckpoint)
from backend.services.audit import append_audit_event
from backend.services.matching_db import run_matching_for_invoice
from backend.services.rules import make_finding
from backend.services.state_machine import assert_transition


class StaleInvoice(Exception):
    pass


def exception_to_dict(e: ExceptionRecord) -> dict:
    ev = dict(e.source_evidence or {})
    return {"id": e.id, "rule_id": e.rule_id, "severity": e.severity, "outcome": ev.pop("outcome", "fail"), "message": ev.pop("message", None),
            "expected": e.expected_value, "actual": e.actual_value, "difference": e.difference, "evidence": ev}


def make_db_tools(session_factory, vendor_client, actor_label: str = "system:workflow") -> dict:
    scope = lambda: session_scope(session_factory)

    def list_findings(invoice_id):
        with scope() as s:
            rows = s.scalars(select(ExceptionRecord).where(ExceptionRecord.invoice_id == invoice_id, ExceptionRecord.status == "OPEN").order_by(ExceptionRecord.id))
            return [exception_to_dict(e) for e in rows]

    def get_invoice_summary(invoice_id):
        with scope() as s:
            inv = s.get(Invoice, invoice_id)
            if inv is None:
                raise NotFound(f"invoice {invoice_id} not found")
            has_po = bool(inv.po_number and s.scalar(select(PurchaseOrder.id).where(PurchaseOrder.po_number == inv.po_number)))
            has_grn = bool(inv.grn_number and s.scalar(select(GoodsReceipt.id).where(GoodsReceipt.grn_number == inv.grn_number)))
            text = lambda v: None if v is None else str(v)
            return {"status": inv.status, "is_scanned": (inv.document_kind or "").startswith("scanned"), "has_po": has_po, "has_grn": has_grn,
                    "invoice": {k: text(getattr(inv, k)) for k in ("invoice_number", "vendor_name_raw", "currency", "subtotal", "tax_total", "grand_total")}}

    def verify_vendor(invoice_id):
        with scope() as s:
            inv = s.get(Invoice, invoice_id)
            vendor = s.get(Vendor, inv.vendor_id) if inv.vendor_id else None
            tax_id = inv.vendor_tax_id_raw or (vendor.tax_id if vendor else None)
            bank = inv.bank_account_raw or (vendor.bank_account if vendor else None)
            code = vendor.vendor_code if vendor else None
        if not tax_id:
            return {"status": "NOT_FOUND"}
        key = f"vv-{invoice_id}-{uuid.uuid4().hex[:12]}"
        try:
            result = vendor_client.verify(tax_id=tax_id, bank_account=bank, vendor_code=code)
        except IntegrationUnavailable as exc:
            with scope() as s:
                s.add(IntegrationRecord(integration="vendor_verification", invoice_id=invoice_id, idempotency_key=key, status="UNAVAILABLE", attempts=exc.attempts))
            raise
        with scope() as s:
            s.add(IntegrationRecord(integration="vendor_verification", invoice_id=invoice_id, idempotency_key=key, status=result["status"],
                                    http_status=result.get("_http_status"), attempts=result.get("_attempts", 1),
                                    response_payload={k: v for k, v in result.items() if not k.startswith("_")}))
        return {"status": result["status"], "tax_id_status": result.get("tax_id_status"), "bank_status": result.get("bank_status")}

    def run_matching(invoice_id):
        with scope() as s:
            run_matching_for_invoice(s, invoice_id, actor_label=actor_label)
        return list_findings(invoice_id)

    def record_exception(invoice_id, rule_id, message, expected, actual):
        f = make_finding(rule_id, message, expected=expected, actual=actual)
        with scope() as s:
            row = ExceptionRecord(invoice_id=invoice_id, exception_type=f.exception_type, severity=f.severity, rule_id=rule_id, expected_value=f.expected,
                                  actual_value=f.actual, source_evidence={"message": message, "outcome": f.outcome}, status="OPEN")
            s.add(row)
            s.flush()
            return exception_to_dict(row)

    def save_explanation(invoice_id, explanation, usage):
        with scope() as s:
            s.add(AiOutput(invoice_id=invoice_id, kind="risk_explanation", source=explanation["source"], summary=explanation["summary"],
                           items=explanation["items"], caveats=explanation["caveats"],
                           verification={k: explanation.get(k) for k in ("verified", "problems", "attempts", "fallback_reason", "label")}))
            for u in usage:
                cost = Decimal(u["cost_usd"]) if u.get("cost_usd") is not None else None
                s.add(LlmUsage(invoice_id=invoice_id, agent="risk_explainer", provider=u["provider"], model=u.get("model"), source="model",
                               prompt_tokens=u.get("prompt_tokens"), completion_tokens=u.get("completion_tokens"), cost_usd=cost,
                               latency_ms=u.get("latency_ms"), outcome="ok"))
            if explanation["source"] == "template":
                s.add(LlmUsage(invoice_id=invoice_id, agent="risk_explainer", provider="template", model=None, source="template",
                               outcome=(explanation.get("fallback_reason") or "ok")[:20]))

    def set_status(invoice_id, new_status):
        with scope() as s:
            inv = s.get(Invoice, invoice_id)
            assert_transition(inv.status, new_status)
            done = s.execute(update(Invoice).where(Invoice.id == invoice_id, Invoice.status == inv.status, Invoice.version == inv.version)
                             .values(status=new_status, version=Invoice.version + 1))
            if done.rowcount != 1:
                raise StaleInvoice("invoice changed while updating its status")
            append_audit_event(s, actor_id=None, actor_label=actor_label, action="STATUS_CHANGED", entity_type="invoice", entity_id=invoice_id,
                               tool_result={"from": inv.status, "to": new_status})

    def append_audit(invoice_id, action, tool_result):
        with scope() as s:
            append_audit_event(s, actor_id=None, actor_label=actor_label, action=action, entity_type="invoice", entity_id=invoice_id, tool_result=tool_result)

    def save_checkpoint(invoice_id, thread_id, node, state, retry_count):
        with scope() as s:
            s.add(WorkflowCheckpoint(invoice_id=invoice_id, thread_id=thread_id, node=node, state=state, retry_count=retry_count))

    def load_events(invoice_id):
        with scope() as s:
            rows = s.scalars(select(AuditEvent).where(AuditEvent.entity_type == "invoice", AuditEvent.entity_id == str(invoice_id)).order_by(AuditEvent.id))
            return [{"id": e.id, "created_at": e.created_at.isoformat(timespec="seconds"), "actor_label": e.actor_label, "action": e.action,
                     "entity_type": e.entity_type, "entity_id": e.entity_id, "decision": e.decision, "tool_result": e.tool_result} for e in rows]

    return {"get_invoice_summary": get_invoice_summary, "verify_vendor": verify_vendor, "run_matching": run_matching, "list_findings": list_findings,
            "record_exception": record_exception, "save_explanation": save_explanation, "set_status": set_status, "append_audit": append_audit,
            "save_checkpoint": save_checkpoint, "load_events": load_events}


def latest_checkpoint(session_factory, invoice_id: int):
    """(node, state) of the most recent completed node, or None. Used to resume an interrupted workflow."""
    with session_scope(session_factory) as s:
        row = s.scalar(select(WorkflowCheckpoint).where(WorkflowCheckpoint.invoice_id == invoice_id).order_by(WorkflowCheckpoint.id.desc()).limit(1))
        return (row.node, row.state) if row else None
