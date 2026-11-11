"""Human review decisions. Authorization, state and duplicate-click protection are enforced HERE (backend),
never only in the UI. The caller commits the surrounding transaction (use session_scope)."""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.errors import NotFound
from backend.core.constants import REVIEW_DECISIONS
from backend.models import Document, ExceptionRecord, Invoice, Review
from backend.services.audit import append_audit_event
from backend.services.state_machine import assert_transition

REVIEW_ROLES = ("admin", "reviewer")
NEW_STATUS = {"approve": "APPROVED", "reject": "REJECTED", "request_documents": "DOCUMENTS_REQUESTED"}


class PermissionDenied(Exception):
    pass


class InvalidState(Exception):
    """The invoice is not in a state that allows this action (HTTP 409)."""


class ValidationFailed(Exception):
    pass


class Conflict(Exception):
    pass


def record_decision(session: Session, *, invoice_id: int, reviewer_id: int, reviewer_role: str, decision: str,
                    comment: str | None, idempotency_key: str) -> Review:
    if reviewer_role not in REVIEW_ROLES:
        raise PermissionDenied("Only reviewers and administrators can record decisions.")
    if decision not in REVIEW_DECISIONS:
        raise ValidationFailed(f"decision must be one of {REVIEW_DECISIONS}")
    key = (idempotency_key or "").strip()
    if not key or len(key) > 80:
        raise ValidationFailed("an idempotency key of 1-80 characters is required")
    comment = (comment or "").strip()

    existing = session.scalar(select(Review).where(Review.idempotency_key == key))
    if existing is not None:  # same click sent twice: return the original result, change nothing
        if (existing.invoice_id, existing.reviewer_id, existing.decision) != (invoice_id, reviewer_id, decision):
            raise Conflict("this idempotency key was already used for a different action")
        return existing

    inv = session.get(Invoice, invoice_id)
    if inv is None:
        raise NotFound(f"invoice {invoice_id} not found")
    if inv.status != "AWAITING_REVIEW":
        raise InvalidState(f"invoice is {inv.status}; only invoices awaiting review can be decided")
    if decision != "approve" and len(comment) < 5:
        raise ValidationFailed("a comment of at least 5 characters is required to reject or request documents")
    open_serious = session.scalar(select(func.count(ExceptionRecord.id)).where(
        ExceptionRecord.invoice_id == invoice_id, ExceptionRecord.status == "OPEN", ExceptionRecord.severity.in_(("high", "critical")))) or 0
    if decision == "approve":
        if open_serious and len(comment) < 10:
            raise ValidationFailed("approving with open high/critical exceptions requires a written justification (10+ characters)")
        doc = session.get(Document, inv.document_id) if inv.document_id else None
        if doc is not None and doc.uploaded_by == reviewer_id and reviewer_role != "admin":
            raise PermissionDenied("segregation of duties: you cannot approve an invoice you uploaded")

    new_status = NEW_STATUS[decision]
    assert_transition(inv.status, new_status)
    done = session.execute(update(Invoice).where(Invoice.id == invoice_id, Invoice.status == "AWAITING_REVIEW", Invoice.version == inv.version)
                           .values(status=new_status, version=Invoice.version + 1))
    if done.rowcount != 1:
        raise Conflict("the invoice was changed by someone else; reload and try again")
    review = Review(invoice_id=invoice_id, reviewer_id=reviewer_id, decision=decision, comment=comment or None, idempotency_key=key)
    session.add(review)
    try:
        session.flush()
    except IntegrityError:
        raise Conflict("duplicate action detected") from None
    append_audit_event(session, actor_id=reviewer_id, actor_label=f"user:{reviewer_id}:{reviewer_role}", action="REVIEW_DECISION",
                       entity_type="invoice", entity_id=invoice_id, decision=decision,
                       tool_result={"review_id": review.id, "from": "AWAITING_REVIEW", "to": new_status, "open_high_or_critical": open_serious},
                       details={"comment": comment})
    return review
