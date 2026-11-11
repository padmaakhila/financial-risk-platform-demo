"""Append-only audit trail with a SHA-256 hash chain.

Limitation (be honest in documentation): an administrator with direct database access
can still rewrite rows *and* recompute the chain. The chain makes casual or partial
tampering detectable; it is not cryptographic immutability. Concurrent writers can in
theory fork the chain; the SQLite single-writer lock makes that unlikely locally.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.entities import AuditEvent, utcnow

GENESIS = "0" * 64


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _hash(prev: str, payload: dict) -> str:
    return hashlib.sha256((prev + _canonical(payload)).encode("utf-8")).hexdigest()


def _payload(ev_fields: dict) -> dict:
    return {k: ev_fields[k] for k in ("actor_id", "actor_label", "action", "entity_type", "entity_id",
                                      "decision", "tool_result", "details", "created_at")}


def append_audit_event(session: Session, *, actor_id: int | None, actor_label: str, action: str,
                       entity_type: str, entity_id, decision: str | None = None,
                       tool_result: dict | None = None, details: dict | None = None) -> AuditEvent:
    last = session.execute(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1)).scalar_one_or_none()
    prev = last.event_hash if last else GENESIS
    created = utcnow()
    fields = dict(actor_id=actor_id, actor_label=actor_label, action=action, entity_type=entity_type,
                  entity_id=str(entity_id), decision=decision, tool_result=tool_result, details=details,
                  created_at=created.isoformat())
    event = AuditEvent(**{**fields, "created_at": created}, prev_hash=prev, event_hash=_hash(prev, _payload(fields)))
    session.add(event)
    session.flush()
    return event


def verify_audit_chain(session: Session) -> tuple[bool, int | None]:
    """Return (ok, first_bad_event_id)."""
    prev = GENESIS
    for ev in session.execute(select(AuditEvent).order_by(AuditEvent.id)).scalars():
        fields = dict(actor_id=ev.actor_id, actor_label=ev.actor_label, action=ev.action, entity_type=ev.entity_type,
                      entity_id=ev.entity_id, decision=ev.decision, tool_result=ev.tool_result, details=ev.details,
                      created_at=ev.created_at.isoformat())
        if ev.prev_hash != prev or ev.event_hash != _hash(prev, _payload(fields)):
            return False, ev.id
        prev = ev.event_hash
    return True, None
