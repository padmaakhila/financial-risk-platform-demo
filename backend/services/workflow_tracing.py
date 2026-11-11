
"""Best-effort Langfuse + durable PostgreSQL workflow/tool tracing.
No invoice payloads are logged.
"""
from __future__ import annotations

import logging
import time
import uuid

from backend.database.session import session_scope
from backend.models import WorkflowTrace

log = logging.getLogger("workflow.tracing")


class WorkflowTraceRecorder:
    def __init__(self, factory, job_id: str, invoice_id: int | None, engine: str, settings):
        self.factory = factory
        self.job_id = str(job_id)
        self.invoice_id = invoice_id
        self.engine = engine
        self.trace_id = uuid.uuid4().hex
        self.langfuse_trace_id = None
        self._lf = None

        if settings.langfuse_enabled:
            try:
                from langfuse import Langfuse

                self._lf = Langfuse(
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key,
                    host=settings.langfuse_host,
                )

                self._lf_trace = self._lf.start_observation(
                    name="financial-risk-invoice-workflow",
                    as_type="span",
                    metadata={
                        "job_id": self.job_id,
                        "invoice_id": self.invoice_id,
                        "engine": self.engine,
                    },
                )
                self.langfuse_trace_id = self._lf_trace.trace_id
            except Exception:
                log.exception(
                    "Langfuse initialization failed; PostgreSQL tracing remains enabled"
                )
                self._lf = None
                self._lf_trace = None

        else:
            self._lf_trace = None

    def record(
        self,
        event_type: str,
        name: str,
        status: str,
        duration_ms: int | None = None,
        details: dict | None = None,
    ):
        safe = dict(details or {})

        try:
            with session_scope(self.factory) as s:
                s.add(
                    WorkflowTrace(
                        trace_id=self.trace_id,
                        job_id=self.job_id,
                        invoice_id=self.invoice_id,
                        engine=self.engine,
                        event_type=event_type,
                        name=name,
                        status=status,
                        duration_ms=duration_ms,
                        details=safe,
                        langfuse_trace_id=self.langfuse_trace_id,
                    )
                )
        except Exception:
            log.exception("Could not persist workflow trace row")

        if self._lf_trace is not None:
            try:
                span = self._lf_trace.start_observation(
                    name=name,
                    as_type="span",
                    input={"event_type": event_type},
                    metadata=safe,
                )
                span.update(
                    output={
                        "status": status,
                        "duration_ms": duration_ms,
                    }
                )
                span.end()
            except Exception:
                log.exception("Could not send span to Langfuse")

    def tool_call(self, entry: dict):
        self.record(
            "tool_call",
            str(entry.get("tool", "unknown")),
            "error" if not entry.get("ok") else "ok",
            entry.get("duration_ms"),
            {
                "argument_names": entry.get("args", []),
                "invoice_id": entry.get("invoice_id"),
                "error_type": entry.get("error"),
            },
        )

    def close(self, status: str, error_type: str | None = None):
        self.record(
            "workflow",
            "invoice_workflow",
            status,
            details={"error_type": error_type},
        )

        if self._lf_trace is not None:
            try:
                self._lf_trace.end()
            except Exception:
                log.exception("Langfuse trace end failed")

        if self._lf is not None:
            try:
                self._lf.flush()
            except Exception:
                log.exception("Langfuse flush failed")
