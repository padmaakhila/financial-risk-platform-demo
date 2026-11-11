"""Payment posting. The ONLY code path that can call the ERP, and it requires a recorded human approval.

Safety properties (each covered by tests):
  * no payment unless the invoice is APPROVED/PAYMENT_PENDING AND its latest review is an 'approve'
  * idempotency key = pay-<invoice>-<review>; retries never create a second ERP payment or a second record
  * ERP outage / timeout leaves the invoice PAYMENT_PENDING (never PAID) and the case can be retried safely
  * the ERP call happens outside the database transaction, so an outage cannot corrupt business records"""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from backend.core.errors import NotFound
from backend.database.session import session_scope
from backend.integrations.clients import IntegrationRejected, IntegrationUnavailable
from backend.models import IntegrationRecord, Invoice, Review, Vendor
from backend.services.audit import append_audit_event
from backend.services.review import PermissionDenied, ValidationFailed
from backend.services.state_machine import assert_transition


class ApprovalRequired(Exception):
    """No recorded human approval exists for this invoice (HTTP 409, code APPROVAL_REQUIRED)."""


class PaymentError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if not k.startswith("_")}


def pay_invoice(session_factory, erp_client, *, invoice_id: int, actor_id: int, actor_role: str) -> dict:
    if actor_role not in ("admin", "reviewer"):
        raise PermissionDenied("Only reviewers and administrators can release payments.")
    label = f"user:{actor_id}:{actor_role}"

    with session_scope(session_factory) as s:  # ---- transaction 1: check approval, reserve the payment record
        inv = s.get(Invoice, invoice_id)
        if inv is None:
            raise NotFound(f"invoice {invoice_id} not found")
        review = s.scalar(select(Review).where(Review.invoice_id == invoice_id).order_by(Review.id.desc()).limit(1))
        if inv.status not in ("APPROVED", "PAYMENT_PENDING", "PAID") or review is None or review.decision != "approve":
            append_audit_event(s, actor_id=actor_id, actor_label=label, action="PAYMENT_BLOCKED", entity_type="invoice", entity_id=invoice_id,
                               tool_result={"reason": "no recorded approval", "status": inv.status})
            s.commit()  # keep the audit record of the blocked attempt
            raise ApprovalRequired("A recorded human approval is required before any payment can be posted.")
        if inv.grand_total is None or not inv.currency or not inv.invoice_number:
            raise ValidationFailed("invoice number, currency and grand total are required to post a payment")
        key = f"pay-{invoice_id}-{review.id}"
        rec = s.scalar(select(IntegrationRecord).where(IntegrationRecord.idempotency_key == key))
        if rec is not None and rec.status == "SUCCEEDED":
            return {"status": "PAID", "payment_id": (rec.response_payload or {}).get("payment_id"), "replayed": True}
        vendor = s.get(Vendor, inv.vendor_id) if inv.vendor_id else None
        if vendor is None:
            raise ValidationFailed("the invoice has no resolved vendor; resolve the vendor before paying")
        if inv.status == "PAID" and rec is None:
            raise PaymentError("invoice is marked paid but has no payment record; manual investigation required")
        payload = {"invoice_number": inv.invoice_number, "vendor_code": vendor.vendor_code, "amount": str(inv.grand_total),
                   "currency": inv.currency, "approval_id": str(review.id)}
        if inv.status == "APPROVED":
            assert_transition("APPROVED", "PAYMENT_PENDING")
            s.execute(update(Invoice).where(Invoice.id == invoice_id, Invoice.status == "APPROVED").values(status="PAYMENT_PENDING", version=Invoice.version + 1))
        if rec is None:
            s.add(IntegrationRecord(integration="erp_payment", invoice_id=invoice_id, idempotency_key=key, request_payload=payload, status="PENDING", attempts=0))
            try:
                s.flush()
            except IntegrityError:  # a concurrent request reserved it first; that one will finish the job
                s.rollback()
                return {"status": "PAYMENT_PENDING", "retry": True, "reason": "another request is already processing this payment"}
            append_audit_event(s, actor_id=actor_id, actor_label=label, action="PAYMENT_REQUESTED", entity_type="invoice", entity_id=invoice_id,
                               tool_result={"idempotency_key": key, "approval_review_id": review.id})

    try:  # ---- ERP call, outside any transaction
        result = erp_client.post_payment(payload, key)
    except IntegrationUnavailable as exc:
        with session_scope(session_factory) as s:
            rec = s.scalar(select(IntegrationRecord).where(IntegrationRecord.idempotency_key == key))
            rec.attempts += exc.attempts
            append_audit_event(s, actor_id=actor_id, actor_label=label, action="PAYMENT_DEFERRED", entity_type="invoice", entity_id=invoice_id,
                               tool_result={"reason": "ERP unavailable", "attempts": exc.attempts})
        return {"status": "PAYMENT_PENDING", "retry": True, "reason": "The ERP is unavailable; the payment stays pending and can be retried safely."}
    except IntegrationRejected as exc:
        with session_scope(session_factory) as s:
            rec = s.scalar(select(IntegrationRecord).where(IntegrationRecord.idempotency_key == key))
            rec.status, rec.http_status, rec.response_payload = "FAILED", exc.status, exc.body
            append_audit_event(s, actor_id=actor_id, actor_label=label, action="PAYMENT_REJECTED", entity_type="invoice", entity_id=invoice_id,
                               tool_result={"http_status": exc.status})
        raise PaymentError("The ERP rejected the payment request.", exc.status) from None

    with session_scope(session_factory) as s:  # ---- transaction 2: record success
        rec = s.scalar(select(IntegrationRecord).where(IntegrationRecord.idempotency_key == key))
        rec.status, rec.http_status, rec.response_payload = "SUCCEEDED", result.get("_http_status"), _clean(result)
        rec.attempts += result.get("_attempts", 1)
        assert_transition("PAYMENT_PENDING", "PAID")
        s.execute(update(Invoice).where(Invoice.id == invoice_id, Invoice.status == "PAYMENT_PENDING").values(status="PAID", version=Invoice.version + 1))
        append_audit_event(s, actor_id=actor_id, actor_label=label, action="PAYMENT_POSTED", entity_type="invoice", entity_id=invoice_id,
                           tool_result={"payment_id": result.get("payment_id"), "replayed": result.get("replayed", False)})
    return {"status": "PAID", "payment_id": result.get("payment_id"), "replayed": result.get("replayed", False)}
