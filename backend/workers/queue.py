"""Persistent job queue on the application database (no Redis/Celery). Claiming is an atomic conditional UPDATE, so
two workers can never run the same job; a dead worker's job is recovered by heartbeat timeout."""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import or_, select, update

from backend.database.session import session_scope
from backend.models import BackgroundJob, utcnow

OPEN = ("QUEUED", "RUNNING", "RETRYING")


def backoff_seconds(attempts: int) -> int:
    return min(300, 10 * 2 ** max(0, attempts - 1))


def enqueue(session, job_type: str, *, invoice_id: int | None = None, document_id: int | None = None, payload: dict | None = None,
            max_attempts: int = 3) -> str:
    """Add a job inside the caller's transaction. An identical open job is reused (duplicate-click protection)."""
    q = select(BackgroundJob).where(BackgroundJob.job_type == job_type, BackgroundJob.status.in_(OPEN))
    q = q.where(BackgroundJob.invoice_id == invoice_id) if invoice_id is not None else q.where(BackgroundJob.invoice_id.is_(None))
    q = q.where(BackgroundJob.document_id == document_id) if document_id is not None else q.where(BackgroundJob.document_id.is_(None))
    existing = session.scalar(q.limit(1))
    if existing:
        return existing.id
    job = BackgroundJob(id=uuid.uuid4().hex[:24], job_type=job_type, invoice_id=invoice_id, document_id=document_id, payload=payload,
                        status="QUEUED", max_attempts=max_attempts)
    session.add(job)
    session.flush()
    return job.id


class JobQueue:
    def __init__(self, session_factory, clock=utcnow):
        self.factory, self.clock = session_factory, clock

    def claim(self, worker_id: str) -> dict | None:
        now = self.clock()
        with session_scope(self.factory) as s:
            candidates = s.scalars(select(BackgroundJob).where(BackgroundJob.status.in_(("QUEUED", "RETRYING")),
                                                               or_(BackgroundJob.run_after.is_(None), BackgroundJob.run_after <= now))
                                   .order_by(BackgroundJob.created_at).limit(5)).all()
            for job in candidates:
                won = s.execute(update(BackgroundJob).where(BackgroundJob.id == job.id, BackgroundJob.status == job.status)
                                .values(status="RUNNING", locked_by=worker_id, started_at=now, heartbeat_at=now, attempts=BackgroundJob.attempts + 1))
                if won.rowcount == 1:
                    s.flush()
                    s.expire_all()
                    j = s.get(BackgroundJob, job.id)
                    return {"id": j.id, "job_type": j.job_type, "invoice_id": j.invoice_id, "document_id": j.document_id, "payload": j.payload,
                            "attempts": j.attempts, "max_attempts": j.max_attempts}
        return None

    def heartbeat(self, job_id: str, progress: int | None = None) -> None:
        with session_scope(self.factory) as s:
            vals = {"heartbeat_at": self.clock()}
            if progress is not None:
                vals["progress_pct"] = progress
            s.execute(update(BackgroundJob).where(BackgroundJob.id == job_id).values(**vals))

    def complete(self, job_id: str) -> None:
        with session_scope(self.factory) as s:
            s.execute(update(BackgroundJob).where(BackgroundJob.id == job_id).values(status="SUCCEEDED", finished_at=self.clock(), progress_pct=100,
                                                                                       error_class=None, error_message=None, locked_by=None))

    def fail(self, job_id: str, exc: Exception, retryable: bool) -> str:
        """Retry (with back-off) only retryable errors and only while attempts remain; otherwise mark FAILED. Returns the new status."""
        now = self.clock()
        with session_scope(self.factory) as s:
            job = s.get(BackgroundJob, job_id)
            retry = retryable and job.attempts < job.max_attempts
            job.status = "RETRYING" if retry else "FAILED"
            job.retryable, job.error_class, job.error_message = retryable, type(exc).__name__, str(exc)[:500]
            job.run_after = now + timedelta(seconds=backoff_seconds(job.attempts)) if retry else None
            job.finished_at = None if retry else now
            job.locked_by = None
            return job.status

    def recover_stale(self, older_than_seconds: int = 300) -> int:
        """Jobs whose worker vanished (no heartbeat) go back to the queue, or fail if out of attempts."""
        cutoff = self.clock() - timedelta(seconds=older_than_seconds)
        n = 0
        with session_scope(self.factory) as s:
            for job in s.scalars(select(BackgroundJob).where(BackgroundJob.status == "RUNNING", BackgroundJob.heartbeat_at < cutoff)):
                job.error_class, job.error_message, job.locked_by, job.retryable = "WorkerLost", "worker stopped responding", None, True
                if job.attempts < job.max_attempts:
                    job.status, job.run_after = "RETRYING", None
                else:
                    job.status, job.finished_at = "FAILED", self.clock()
                n += 1
        return n
