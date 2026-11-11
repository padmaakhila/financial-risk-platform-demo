"""Dashboard and monitoring aggregates computed from the database (counts and amounts come from the same rows as reports)."""
from __future__ import annotations

from sqlalchemy import func, select

from backend.core.metrics import aging_buckets, job_stats, llm_stats
from backend.models import BackgroundJob, Document, ExceptionRecord, Invoice, LlmUsage, utcnow

PENDING = ("AWAITING_REVIEW", "DOCUMENTS_REQUESTED", "NEEDS_MANUAL_ENTRY")


def job_rows(db) -> list[dict]:
    return [{"status": j.status, "started_at": j.started_at, "finished_at": j.finished_at, "attempts": j.attempts}
            for j in db.scalars(select(BackgroundJob))]


def dashboard_summary(db, now=None) -> dict:
    now = now or utcnow()
    by_status = dict(db.execute(select(Invoice.status, func.count(Invoice.id)).group_by(Invoice.status)).all())
    exc_rows = db.execute(select(ExceptionRecord.rule_id, ExceptionRecord.exception_type, ExceptionRecord.severity, ExceptionRecord.invoice_id)
                          .where(ExceptionRecord.status == "OPEN")).all()
    by_type, by_sev, dup_invoices = {}, {}, set()
    for rule, etype, sev, inv_id in exc_rows:
        by_type[etype] = by_type.get(etype, 0) + 1
        by_sev[sev] = by_sev.get(sev, 0) + 1
        if rule.startswith("DUP_"):
            dup_invoices.add(inv_id)
    pending_dates = []
    for inv_date, created in db.execute(select(Invoice.invoice_date, Invoice.created_at).where(Invoice.status.in_(PENDING))):
        pending_dates.append(__import__("datetime").datetime.combine(inv_date, __import__("datetime").time()) if inv_date else created)
    return {"documents_uploaded": db.scalar(select(func.count(Document.id))) or 0, "invoices_total": sum(by_status.values()),
            "invoices_by_status": by_status, "pending_reviews": by_status.get("AWAITING_REVIEW", 0), "suspected_duplicates": len(dup_invoices),
            "exceptions_by_type": by_type, "exceptions_by_severity": by_sev, "open_exceptions": len(exc_rows),
            "aging_pending_days_since_invoice_date": aging_buckets(pending_dates, now), "jobs": job_stats(job_rows(db)),
            "ai": llm_stats([{"source": u.source, "outcome": u.outcome, "prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens,
                              "cost_usd": u.cost_usd, "latency_ms": u.latency_ms} for u in db.scalars(select(LlmUsage))])}
