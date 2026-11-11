"""Job handlers: document extraction and the invoice workflow (with resume after interruption)."""
from __future__ import annotations

import logging

from sqlalchemy import select

from backend.agents.tools import ToolRegistry
from backend.agents.workflow import (
    WorkflowConfig,
    WorkflowContext,
    WorkflowError,
    build_langgraph,
    initial_state,
    resume_workflow,
    run_workflow,
)
from backend.agents.workflow_db import latest_checkpoint, make_db_tools
from backend.database.session import session_scope
from backend.models import Document, Invoice
from backend.services.audit import append_audit_event
from backend.services.extraction import extract_document
from backend.services.extraction_db import save_extraction
from backend.services.upload_validation import resolve_stored_path
from backend.workers.queue import enqueue
from backend.services.workflow_tracing import WorkflowTraceRecorder
from backend.workers.worker import JobFailure, classify_error

log = logging.getLogger("handlers")


def make_handlers(
    factory,
    settings,
    provider,
    vendor_client,
    queue,
    engine=None,
    validator=None,
) -> dict:
    def process_document(job: dict) -> None:
        with session_scope(factory) as s:
            doc = s.get(Document, job["document_id"])
            if doc is None:
                raise JobFailure("document not found", retryable=False)

            path = resolve_stored_path(settings.upload_dir, doc.stored_filename)
            doc.status = "PROCESSING"

        queue.heartbeat(job["id"], 20)
        result = extract_document(
            path,
            engine=engine,
            tesseract_cmd=settings.tesseract_cmd,
            validator=validator,
        )
        queue.heartbeat(job["id"], 70)

        if result.status == "failed":
            # Internal failure: the job must FAIL, never look successful.
            with session_scope(factory) as s:
                s.get(Document, job["document_id"]).status = "FAILED"

            raise JobFailure(
                f"extraction failed: {result.reason}",
                retryable=False,
            )

        rejected = None

        with session_scope(factory) as s:
            doc = s.get(Document, job["document_id"])

            try:
                out = save_extraction(s, doc, result)
            except ValueError as exc:
                # E.g. PO number already exists: a business problem, not a crash.
                rejected = str(exc)[:200]
                doc.status = "REJECTED"

                append_audit_event(
                    s,
                    actor_id=None,
                    actor_label="system:extraction_agent",
                    action="IMPORT_REJECTED",
                    entity_type="document",
                    entity_id=doc.id,
                    tool_result={"reason": rejected},
                )
            else:
                if out.get("invoice_id") and result.status == "ok":
                    enqueue(s, "process_invoice", invoice_id=out["invoice_id"])

        if rejected:
            # Visible as FAILED, never as success.
            raise JobFailure(
                f"import rejected: {rejected}",
                retryable=False,
            )

    def process_invoice(job: dict) -> None:
        invoice_id = job["invoice_id"]

        workflow_engine = getattr(settings, "workflow_engine", "runner")
        recorder = WorkflowTraceRecorder(factory, job["id"], invoice_id, workflow_engine, settings)
        tools = ToolRegistry(make_db_tools(factory, vendor_client), trace_callback=recorder.tool_call)
        ctx = WorkflowContext(
            tools,
            provider,
            WorkflowConfig(
                llm_timeout=float(settings.llm_timeout_seconds)
            ),
        )

        status = tools.call(
            "get_invoice_summary",
            invoice_id=invoice_id,
        )["status"]

        # This checkpoint is stored by the app's database tools in PostgreSQL.
        cp = latest_checkpoint(factory, invoice_id)

        try:
            if status == "PROCESSING" and cp and cp[0] != "audit":
                # Preserve existing resume behavior: continue after the last
                # completed PostgreSQL checkpoint using the plain runner.
                resume_workflow(ctx, cp[1], cp[0])
                return

            if workflow_engine == "langgraph":
                try:
                    graph = build_langgraph(ctx, heartbeat=lambda _node: queue.heartbeat(job["id"]))
                except (ImportError, RuntimeError, ValueError) as exc:
                    if not getattr(settings, "workflow_fallback", True):
                        raise
                    log.warning("LangGraph could not be built (%s); falling back to runner", type(exc).__name__)
                    recorder.record("fallback", "langgraph_to_runner", "fallback", details={"reason": type(exc).__name__})
                    run_workflow(ctx, initial_state(invoice_id))
                else:
                    # Once invoke starts, nodes may commit external/database effects.
                    # Never restart the runner from step one on a graph runtime error.
                    graph.invoke(initial_state(invoice_id))
            else:
                run_workflow(ctx, initial_state(invoice_id))
            recorder.close("ok")

        except WorkflowError as exc:
            recorder.close("error", type(exc.cause).__name__)
            raise JobFailure(str(exc), retryable=exc.retryable or classify_error(exc.cause)) from exc
        except Exception as exc:
            recorder.close("error", type(exc).__name__)
            raise

    return {
        "process_document": process_document,
        "process_invoice": process_invoice,
    }


def make_failure_hooks(factory) -> dict:
    def invoice_failed(job: dict, exc: Exception) -> None:
        with session_scope(factory) as s:
            inv = s.get(Invoice, job["invoice_id"])

            if inv is not None and inv.status == "PROCESSING":
                inv.status = "FAILED"
                inv.version += 1

            append_audit_event(
                s,
                actor_id=None,
                actor_label="system:worker",
                action="PROCESSING_FAILED",
                entity_type="invoice",
                entity_id=job["invoice_id"],
                tool_result={
                    "error": type(exc).__name__,
                    "attempts": job["attempts"],
                },
            )

    return {"process_invoice": invoice_failed}