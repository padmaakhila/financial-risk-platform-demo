"""Worker and job-queue tests (need SQLAlchemy). Cover claiming, retries with back-off, recovery and honest failure reporting."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.agents.llm import FakeProvider, LLMUnavailable
from backend.core.config import Settings
from backend.database.session import make_engine, session_scope
from backend.integrations.clients import IntegrationUnavailable, VendorVerificationClient
from backend.integrations.mock_server import start_in_thread
from backend.integrations.vendor_mock_core import VendorMock
from backend.models import AuditEvent, BackgroundJob, Base, Document, ExceptionRecord, Invoice
from backend.services.doc_text import invoice_lines_text
from backend.services.extraction import Thresholds
from backend.services.extraction_db import register_document
from backend.services.upload_validation import store_upload, validate_upload
from backend.workers.handlers import make_failure_hooks, make_handlers
from backend.workers.queue import JobQueue, backoff_seconds, enqueue
from backend.workers.worker import JobFailure, Worker, classify_error
from scripts.generate_data import build_dataset
from scripts.generate_documents import write_digital_pdf
from scripts.seed_database import seed

DS = build_dataset(42)


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 1, 12, 0, 0)

    def __call__(self):
        return self.now


@pytest.fixture
def env(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'w.db').as_posix()}")
    Base.metadata.create_all(engine)
    f = sessionmaker(bind=engine, expire_on_commit=False)
    with session_scope(f) as s:
        seed(s, DS)
    clock = Clock()
    return f, JobQueue(f, clock), clock, tmp_path


def add_job(f, job_type="process_invoice", invoice_id=1, document_id=None, max_attempts=3):
    with session_scope(f) as s:
        return enqueue(s, job_type, invoice_id=invoice_id, document_id=document_id, max_attempts=max_attempts)


def job(f, job_id):
    with session_scope(f) as s:
        return s.get(BackgroundJob, job_id)


def test_enqueue_reuses_an_identical_open_job(env):
    f, q, _, _ = env
    a, b = add_job(f), add_job(f)
    assert a == b
    assert add_job(f, invoice_id=2) != a


def test_a_job_can_only_be_claimed_once(env):
    f, q, _, _ = env
    add_job(f)
    first, second = q.claim("w1"), q.claim("w2")
    assert first and first["attempts"] == 1 and second is None


def test_retryable_failure_backs_off_then_runs_again_and_finally_fails(env):
    f, q, clock, _ = env
    jid = add_job(f, max_attempts=2)
    w = Worker(q, {"process_invoice": lambda j: (_ for _ in ()).throw(IntegrationUnavailable("down", 3))})
    assert w.run_once() and job(f, jid).status == "RETRYING"
    assert job(f, jid).retryable is True and job(f, jid).run_after == clock.now + timedelta(seconds=backoff_seconds(1))
    assert q.claim("w") is None  # still backing off
    clock.now += timedelta(seconds=11)
    assert w.run_once() and job(f, jid).status == "FAILED" and job(f, jid).attempts == 2 and job(f, jid).finished_at is not None


def test_non_retryable_failure_fails_immediately_and_is_never_marked_successful(env):
    f, q, _, _ = env
    jid = add_job(f)
    Worker(q, {"process_invoice": lambda j: (_ for _ in ()).throw(ValueError("bad data"))}).run_once()
    j = job(f, jid)
    assert j.status == "FAILED" and j.attempts == 1 and j.error_class == "ValueError" and j.retryable is False


def test_missing_handler_fails_the_job(env):
    f, q, _, _ = env
    jid = add_job(f, job_type="process_invoice")
    Worker(q, {}).run_once()
    assert job(f, jid).status == "FAILED"


def test_success_marks_job_done(env):
    f, q, _, _ = env
    jid = add_job(f)
    Worker(q, {"process_invoice": lambda j: None}).run_once()
    j = job(f, jid)
    assert j.status == "SUCCEEDED" and j.progress_pct == 100 and j.error_class is None


def test_stale_running_jobs_are_recovered_and_exhausted_ones_fail(env):
    f, q, clock, _ = env
    a, b = add_job(f, invoice_id=1), add_job(f, invoice_id=2, max_attempts=1)
    q.claim("dead-worker")
    q.claim("dead-worker")
    clock.now += timedelta(minutes=10)
    assert q.recover_stale(300) == 2
    assert job(f, a).status == "RETRYING" and job(f, a).error_class == "WorkerLost"
    assert job(f, b).status == "FAILED"
    assert q.claim("new-worker")["id"] == a


def test_classify_error():
    assert classify_error(IntegrationUnavailable("x")) and classify_error(TimeoutError()) and classify_error(JobFailure("x", True))
    assert not classify_error(ValueError("x")) and not classify_error(JobFailure("x", False))


def make_handlers_for(f, tmp, provider=None, validator=None):
    settings = Settings(upload_dir=tmp / "uploads", llm_timeout_seconds=1)
    core = VendorMock.from_dataset(DS)
    srv, url = start_in_thread(core)
    q = JobQueue(f)
    return make_handlers(f, settings, provider or FakeProvider([LLMUnavailable("no model")]), VendorVerificationClient(url, timeout=0.5, sleep=lambda s: None), q,
                         validator=validator), srv, q, settings


def test_invoice_job_runs_the_workflow_to_review(env):
    f, _, _, tmp = env
    handlers, srv, q, _ = make_handlers_for(f, tmp)
    try:
        with session_scope(f) as s:
            inv_id = s.scalar(select(Invoice.id).where(Invoice.invoice_number == "INV-000001"))
        add_job(f, invoice_id=inv_id)
        hooks = make_failure_hooks(f)
        assert Worker(q, handlers, hooks).run_once()
        with session_scope(f) as s:
            assert s.get(Invoice, inv_id).status == "AWAITING_REVIEW"
    finally:
        srv.shutdown()


def test_invoice_job_marks_invoice_failed_after_final_attempt(env):
    f, _, _, tmp = env
    handlers, srv, q, _ = make_handlers_for(f, tmp)
    try:
        with session_scope(f) as s:
            inv_id = s.scalar(select(Invoice.id).where(Invoice.invoice_number == "INV-000002"))
        handlers["process_invoice"]  # real handler exists; replace the workflow with a failing one to test the hook path
        failing = {"process_invoice": lambda j: (_ for _ in ()).throw(JobFailure("boom", False))}
        with session_scope(f) as s:
            s.get(Invoice, inv_id).status = "PROCESSING"
        jid = add_job(f, invoice_id=inv_id)
        Worker(q, failing, make_failure_hooks(f)).run_once()
        with session_scope(f) as s:
            assert s.get(Invoice, inv_id).status == "FAILED"
            assert s.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.action == "PROCESSING_FAILED")) == 1
        assert job(f, jid).status == "FAILED"
    finally:
        srv.shutdown()


def upload(f, tmp, lines_or_bytes, name="doc.pdf"):
    path = tmp / "src.pdf"
    if isinstance(lines_or_bytes, list):
        write_digital_pdf(path, lines_or_bytes)
        data = path.read_bytes()
    else:
        data = lines_or_bytes
    v = validate_upload(name, data, "application/pdf", max_bytes=10_000_000)
    store_upload(tmp / "uploads", v, data)
    with session_scope(f) as s:
        return register_document(s, v, uploaded_by=None).id


def test_document_job_extracts_creates_invoice_and_queues_the_workflow(env):
    f, _, _, tmp = env
    handlers, srv, q, _ = make_handlers_for(f, tmp)
    try:
        inv = next(i for i in DS["invoices"] if i["scenario_code"] == "S04_LINE_TOTAL")
        doc_id = upload(f, tmp, invoice_lines_text(inv))
        add_job(f, "process_document", invoice_id=None, document_id=doc_id)
        assert Worker(q, handlers).run_once()
        with session_scope(f) as s:
            new = s.scalar(select(Invoice).where(Invoice.document_id == doc_id))
            assert new.data_source == "extracted" and new.invoice_number == inv["invoice_number"] and new.grand_total == inv["grand_total"]
            assert s.get(Document, doc_id).status == "EXTRACTED" and len(new.lines) == len(inv["lines"])
            queued = s.scalar(select(BackgroundJob).where(BackgroundJob.invoice_id == new.id, BackgroundJob.job_type == "process_invoice"))
            assert queued.status == "QUEUED"
        assert Worker(q, handlers, make_failure_hooks(f)).run_once()  # now process the invoice itself
        with session_scope(f) as s:
            rules = {e.rule_id for e in s.scalars(select(ExceptionRecord).where(ExceptionRecord.invoice_id == new.id))}
            assert "ARITH_LINE_TOTAL" in rules and s.get(Invoice, new.id).status == "AWAITING_REVIEW"
    finally:
        srv.shutdown()


def test_unreadable_document_goes_to_manual_entry_with_visible_exception(env):
    f, _, _, tmp = env
    handlers, srv, q, _ = make_handlers_for(f, tmp)
    try:
        doc_id = upload(f, tmp, b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n")  # structurally a PDF but has no readable content
        add_job(f, "process_document", invoice_id=None, document_id=doc_id)
        Worker(q, handlers).run_once()
        with session_scope(f) as s:
            inv = s.scalar(select(Invoice).where(Invoice.document_id == doc_id))
            doc = s.get(Document, doc_id)
        assert (inv is not None and inv.status == "NEEDS_MANUAL_ENTRY") or doc.status in ("FAILED", "NEEDS_MANUAL_ENTRY")
    finally:
        srv.shutdown()


def test_missing_stored_file_fails_the_job_instead_of_succeeding(env):
    f, _, _, tmp = env
    handlers, srv, q, settings = make_handlers_for(f, tmp)
    try:
        doc_id = upload(f, tmp, [f"INVOICE X-1", "Grand total: 5.00", "Subtotal: 5.00"])
        for p in (settings.upload_dir).iterdir():
            p.unlink()
        jid = add_job(f, "process_document", invoice_id=None, document_id=doc_id)
        Worker(q, handlers).run_once()
        assert job(f, jid).status == "FAILED"
        with session_scope(f) as s:
            assert s.get(Document, doc_id).status == "FAILED"
    finally:
        srv.shutdown()


def test_duplicate_po_import_is_rejected_visibly(env):
    f, _, _, tmp = env
    handlers, srv, q, _ = make_handlers_for(f, tmp)
    try:
        from backend.services.doc_text import po_lines_text
        doc_id = upload(f, tmp, po_lines_text(DS["purchase_orders"][0]))  # this PO number is already seeded
        jid = add_job(f, "process_document", invoice_id=None, document_id=doc_id)
        Worker(q, handlers).run_once()
        assert job(f, jid).status == "FAILED" and "already exists" in job(f, jid).error_message
        with session_scope(f) as s:
            assert s.get(Document, doc_id).status == "REJECTED"
    finally:
        srv.shutdown()
