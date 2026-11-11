"""Input validation, request classification, permission scope, read-only guard."""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional

from . import config
from .guardrails import detect_injection

# Reuse the platform's permission helper (no second permission system).
from backend.auth.permissions import can


class InputRejected(Exception):
    """Raised for questions that must not be processed. ``message`` is safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code = code
        self.message = message


class ReadOnlyViolation(RuntimeError):
    pass


_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

_WRITE_VERBS = (
    "approve|reject|pay|release|delete|remove|update|change|modify|edit|set|grant|revoke|mark|"
    "override|execute|submit|reassign|disable|enable|cancel|void|reopen|escalate|assign|add|create|insert|write"
)
_ACTION = re.compile(
    r"^\s*(?:please\s+)?(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?|i\s+(?:want|need)\s+you\s+to\s+|go\s+ahead\s+and\s+)?"
    r"(?:%s)\b" % _WRITE_VERBS, re.I)
_CODE_EXEC = re.compile(
    r"(?is)\b(?:select\s.+\sfrom|drop\s+table|delete\s+from|insert\s+into|update\s+\w+\s+set|truncate\s+table|alter\s+table)\b|"
    r"\b(?:os\.system|subprocess|eval\(|exec\(|rm\s+-rf|powershell|cmd\.exe)\b|\bcurl\s+https?://|\bwget\s+https?://")

REFUSAL_ACTION = ("I'm a read-only assistant. I can explain what the platform has recorded, but I can't approve, "
                  "reject, pay, edit or change anything. Please use the Review & Approval page for decisions.")
REFUSAL_EXEC = ("I can't run SQL, code, shell commands or web requests. I can only look up and explain "
                "records you are authorised to see.")
REFUSAL_INJECTION = ("I can't follow instructions that try to change my rules or reveal my configuration. "
                     "Ask me about an invoice, vendor, PO, GRN, extraction result or risk finding instead.")


def validate_question(question) -> str:
    """Return the cleaned question or raise InputRejected."""
    if not isinstance(question, str):
        raise InputRejected("invalid_type", "The question must be text.")
    q = _CTRL.sub(" ", question)
    q = " ".join(q.split())
    if not q:
        raise InputRejected("empty", "Please type a question.")
    if len(q) > config.MAX_QUESTION_CHARS:
        raise InputRejected("too_long", "The question is too long. Please keep it under %d characters." % config.MAX_QUESTION_CHARS)
    if not any(c.isalnum() for c in q):
        raise InputRejected("invalid", "Please ask a question about an invoice, vendor, PO or GRN.")
    return q


def refusal_for(question: str) -> Optional[str]:
    """Deterministic refusal text, or None if the question may proceed.
    Runs before any retrieval or model call."""
    if detect_injection(question):
        return REFUSAL_INJECTION
    if _CODE_EXEC.search(question):
        return REFUSAL_EXEC
    if _ACTION.search(question):
        return REFUSAL_ACTION
    return None


@dataclass(frozen=True)
class Scope:
    role: str
    records: bool
    evidence: bool
    audit: bool
    bank: bool
    reports: bool
    admin: bool
    queue: bool          # view_queue: used for review decisions/comments


def build_scope(role: str) -> Scope:
    r = role or ""
    return Scope(
        role=r,
        records=can(r, "view_records"),
        evidence=can(r, "view_evidence"),
        audit=can(r, "view_audit"),
        bank=can(r, "view_bank_details"),
        reports=can(r, "view_reports"),
        admin=can(r, "admin"),
        queue=can(r, "view_queue"),
    )


@contextmanager
def read_only_session(db):
    """Defence in depth around the request's SQLAlchemy session:
    1. any ORM flush containing new/changed/deleted objects raises;
    2. on PostgreSQL the transaction is switched to read-only (SET LOCAL);
    3. the transaction is rolled back on exit, so nothing can be committed.
    """
    from sqlalchemy import event, text

    def _block(session, flush_context, instances):
        if session.new or session.deleted or any(session.is_modified(o) for o in session.dirty):
            raise ReadOnlyViolation("The Copilot is read-only.")

    event.listen(db, "before_flush", _block)
    try:
        try:
            bind = db.get_bind()
            if getattr(getattr(bind, "dialect", None), "name", "") == "postgresql":
                db.execute(text("SET LOCAL transaction_read_only = on"))
        except ReadOnlyViolation:
            raise
        except Exception:
            pass  # the ORM guard above stays active
        yield db
    finally:
        try:
            event.remove(db, "before_flush", _block)
        finally:
            try:
                db.rollback()
            except Exception:
                pass
