"""Worker process: claims jobs, runs handlers, records success or failure honestly.
Run (own PowerShell window):  python -m backend.workers.worker"""
from __future__ import annotations

import logging
import os
import socket
import time
from typing import Callable

from backend.workers.queue import JobQueue

log = logging.getLogger("worker")


class JobFailure(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def classify_error(exc: Exception) -> bool:
    """True if retrying later can plausibly help (outages, timeouts, locked database)."""
    from backend.integrations.clients import IntegrationUnavailable
    if isinstance(exc, JobFailure):
        return exc.retryable
    if isinstance(exc, (IntegrationUnavailable, TimeoutError, ConnectionError)):
        return True
    try:
        from sqlalchemy.exc import OperationalError
        if isinstance(exc, OperationalError):
            return True
    except ImportError:
        pass
    return False


class Worker:
    def __init__(self, queue: JobQueue, handlers: dict[str, Callable[[dict], None]], failure_hooks: dict[str, Callable] | None = None,
                 worker_id: str | None = None):
        self.queue, self.handlers, self.hooks = queue, handlers, failure_hooks or {}
        self.id = worker_id or f"{socket.gethostname()}:{os.getpid()}"

    def run_once(self) -> bool:
        job = self.queue.claim(self.id)
        if job is None:
            return False
        extra = {"job_id": job["id"], "invoice_id": job["invoice_id"]}
        log.info("job started: %s attempt %s", job["job_type"], job["attempts"], extra=extra)
        try:
            handler = self.handlers.get(job["job_type"])
            if handler is None:
                raise JobFailure(f"no handler for job type {job['job_type']}", retryable=False)
            handler(job)
        except Exception as exc:  # a job must never be marked successful after an error
            retryable = classify_error(exc)
            status = self.queue.fail(job["id"], exc, retryable)
            log.exception(
                "job failed (%s, retryable=%s): %s",
                status,
                retryable,
                type(exc).__name__,
                extra=extra,
            )
            if status == "FAILED" and job["job_type"] in self.hooks:
                try:
                    self.hooks[job["job_type"]](job, exc)
                except Exception:
                    log.exception("failure hook crashed", extra=extra)
            return True
        self.queue.complete(job["id"])
        log.info("job succeeded", extra=extra)
        return True

    def run_forever(self, poll_seconds: float = 2.0, stale_seconds: int = 300) -> None:
        last_recover = 0.0
        while True:
            if time.monotonic() - last_recover > 60:
                recovered = self.queue.recover_stale(stale_seconds)
                if recovered:
                    log.warning("recovered %s stale job(s)", recovered)
                last_recover = time.monotonic()
            if not self.run_once():
                time.sleep(poll_seconds)


def main() -> None:
    from backend.agents.llm import build_provider
    from backend.core.config import get_settings
    from backend.core.logging_setup import setup_logging
    from backend.database.session import get_session_factory
    from backend.integrations.clients import VendorVerificationClient
    from backend.workers.handlers import make_failure_hooks, make_handlers
    from scripts.init_db import init_db
    s = get_settings()
    setup_logging(s.log_level)
    init_db()
    factory = get_session_factory()
    queue = JobQueue(factory)
    handlers = make_handlers(factory, s, build_provider(s), VendorVerificationClient(s.vendor_mock_url), queue)
    worker = Worker(queue, handlers, make_failure_hooks(factory))
    log.info("worker %s started (LLM provider: %s)", worker.id, s.llm_provider)
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        log.info("worker stopped")


if __name__ == "__main__":
    main()
