"""All SQLAlchemy models. Money is stored as exact decimal text (never float).
Timestamps are naive UTC. Exact duplicate invoices are *allowed* in the table on
purpose: the platform must be able to store and detect them (index, not unique)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from backend.database.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DecimalText(TypeDecorator):
    """Exact Decimal stored as text; refuses floats so rounding errors cannot sneak in."""
    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError("Use Decimal (not float) for money and quantities")
        return str(Decimal(value))

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


Money = DecimalText


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (CheckConstraint("role IN ('admin','reviewer','ap_clerk','auditor')", name="ck_users_role"),)


class Vendor(Base):
    __tablename__ = "vendors"
    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    tax_id: Mapped[str | None] = mapped_column(String(40))
    bank_account: Mapped[str | None] = mapped_column(String(60))
    bank_name: Mapped[str | None] = mapped_column(String(100))
    verification_status: Mapped[str] = mapped_column(String(20), default="UNVERIFIED")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (CheckConstraint("verification_status IN ('VERIFIED','REJECTED','UNVERIFIED','PENDING')", name="ck_vendor_verif"),)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    po_number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True)
    order_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(cascade="all, delete-orphan", order_by="PurchaseOrderLine.line_no")


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[Decimal] = mapped_column(Money)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    tax_rate: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    __table_args__ = (UniqueConstraint("po_id", "line_no", name="uq_po_line"),)


class GoodsReceipt(Base):
    __tablename__ = "goods_receipts"
    id: Mapped[int] = mapped_column(primary_key=True)
    grn_number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    receipt_date: Mapped[date] = mapped_column(Date)
    lines: Mapped[list["GoodsReceiptLine"]] = relationship(cascade="all, delete-orphan", order_by="GoodsReceiptLine.po_line_no")


class GoodsReceiptLine(Base):
    __tablename__ = "goods_receipt_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    grn_id: Mapped[int] = mapped_column(ForeignKey("goods_receipts.id", ondelete="CASCADE"), index=True)
    po_line_no: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(300))
    quantity_received: Mapped[Decimal] = mapped_column(Money)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(80), unique=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    doc_type: Mapped[str] = mapped_column(String(20), default="unknown")
    document_kind: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="UPLOADED")
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, index=True)  # arrival order; duplicates compare to lower seq only
    invoice_number: Mapped[str | None] = mapped_column(String(60))
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"), index=True)
    vendor_name_raw: Mapped[str | None] = mapped_column(String(200))
    vendor_tax_id_raw: Mapped[str | None] = mapped_column(String(40))
    bank_account_raw: Mapped[str | None] = mapped_column(String(60))
    invoice_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    po_number: Mapped[str | None] = mapped_column(String(30), index=True)
    grn_number: Mapped[str | None] = mapped_column(String(30))
    currency: Mapped[str | None] = mapped_column(String(3))
    subtotal: Mapped[Decimal | None] = mapped_column(Money)
    tax_total: Mapped[Decimal | None] = mapped_column(Money)
    grand_total: Mapped[Decimal | None] = mapped_column(Money)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(25), default="RECEIVED", index=True)
    document_kind: Mapped[str | None] = mapped_column(String(30))
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    data_source: Mapped[str] = mapped_column(String(20), default="synthetic")  # synthetic | extracted | manual
    version: Mapped[int] = mapped_column(Integer, default=1)  # optimistic locking for state changes
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    lines: Mapped[list["InvoiceLine"]] = relationship(cascade="all, delete-orphan", order_by="InvoiceLine.line_no")
    __table_args__ = (
        Index("ix_invoice_vendor_number", "vendor_id", "invoice_number"),
        CheckConstraint("status IN ('RECEIVED','PROCESSING','NEEDS_MANUAL_ENTRY','AWAITING_REVIEW','DOCUMENTS_REQUESTED','APPROVED','REJECTED','PAYMENT_PENDING','PAID','FAILED')", name="ck_invoice_status"),
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"),
        index=True,
    )
    line_no: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[Decimal] = mapped_column(Money)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    discount_pct: Mapped[Decimal] = mapped_column(
        Money,
        default=Decimal("0"),
    )
    tax_rate: Mapped[Decimal] = mapped_column(
        Money,
        default=Decimal("0"),
    )
    line_total: Mapped[Decimal] = mapped_column(Money)
    tax_amount: Mapped[Decimal] = mapped_column(Money)

    __table_args__ = (
        UniqueConstraint("invoice_id", "line_no", name="uq_invoice_line"),
        CheckConstraint(
            "CAST(discount_pct AS NUMERIC) >= 0",
            name="ck_line_discount",
        ),
    )
class ExtractedField(Base):
    __tablename__ = "extracted_fields"
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), index=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), index=True)
    field_name: Mapped[str] = mapped_column(String(60))
    value_text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    confidence_method: Mapped[str | None] = mapped_column(String(30))  # pdf_text | ocr_word_conf | llm_estimate | none
    page_number: Mapped[int | None] = mapped_column(Integer)
    source_snippet: Mapped[str | None] = mapped_column(Text)
    bbox: Mapped[dict | None] = mapped_column(JSON)


class ExceptionRecord(Base):
    __tablename__ = "exceptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    exception_type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10), index=True)
    rule_id: Mapped[str] = mapped_column(String(40), index=True)
    expected_value: Mapped[str | None] = mapped_column(Text)
    actual_value: Mapped[str | None] = mapped_column(Text)
    difference: Mapped[str | None] = mapped_column(String(60))
    source_evidence: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(10), default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (CheckConstraint("severity IN ('info','low','medium','high','critical')", name="ck_exc_sev"),
                      CheckConstraint("status IN ('OPEN','RESOLVED','WAIVED')", name="ck_exc_status"))


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (CheckConstraint("decision IN ('approve','reject','request_documents')", name="ck_review_decision"),)


class AuditEvent(Base):
    """Append-only by convention + SHA-256 hash chain (tamper-EVIDENT, not immutable)."""
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    actor_label: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(40))
    decision: Mapped[str | None] = mapped_column(String(30))
    tool_result: Mapped[dict | None] = mapped_column(JSON)
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    prev_hash: Mapped[str] = mapped_column(String(64))
    event_hash: Mapped[str] = mapped_column(String(64), unique=True)
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(40))
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    status: Mapped[str] = mapped_column(String(12), default="QUEUED", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    error_class: Mapped[str | None] = mapped_column(String(60))
    error_message: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool | None] = mapped_column(Boolean)
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict | None] = mapped_column(JSON)
    locked_by: Mapped[str | None] = mapped_column(String(60))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    run_after: Mapped[datetime | None] = mapped_column(DateTime)  # retry back-off: do not start before this time
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (CheckConstraint("status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','RETRYING','CANCELLED')", name="ck_job_status"),)


class WorkflowCheckpoint(Base):
    """Our own readable workflow state per invoice. LangGraph's SqliteSaver keeps its
    own tables (in the same file) for graph internals; this table is what the UI shows."""
    __tablename__ = "workflow_checkpoints"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    thread_id: Mapped[str] = mapped_column(String(60), index=True)
    node: Mapped[str] = mapped_column(String(40))
    state: Mapped[dict | None] = mapped_column(JSON)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IntegrationRecord(Base):
    __tablename__ = "integration_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    integration: Mapped[str] = mapped_column(String(30), index=True)  # erp_payment | vendor_verification
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    request_payload: Mapped[dict | None] = mapped_column(JSON)
    response_payload: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20))
    http_status: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(300))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ScenarioGroundTruth(Base):
    __tablename__ = "scenario_ground_truth"
    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_code: Mapped[str] = mapped_column(String(40), index=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), index=True)
    file_name: Mapped[str | None] = mapped_column(String(255))
    expected: Mapped[dict] = mapped_column(JSON)


class LlmUsage(Base):
    __tablename__ = "llm_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), index=True)
    agent: Mapped[str] = mapped_column(String(30))
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str | None] = mapped_column(String(80))
    source: Mapped[str] = mapped_column(String(12))  # model | template
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Money)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(20))  # ok | timeout | error | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AiOutput(Base):
    """Stored risk explanations and audit summaries. `source` says whether a model or the template wrote it."""
    __tablename__ = "ai_outputs"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # risk_explanation | audit_summary
    source: Mapped[str] = mapped_column(String(12))  # model | template
    summary: Mapped[str] = mapped_column(Text)
    items: Mapped[list | None] = mapped_column(JSON)
    caveats: Mapped[list | None] = mapped_column(JSON)
    verification: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (CheckConstraint("kind IN ('risk_explanation','audit_summary')", name="ck_ai_kind"),
                      CheckConstraint("source IN ('model','template')", name="ck_ai_source"))


class WorkflowTrace(Base):
    """Structured workflow/tool-call trace metadata; payloads are intentionally redacted."""
    __tablename__ = "workflow_traces"
    id: Mapped[int] = mapped_column(primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    job_id: Mapped[str | None] = mapped_column(String(40), index=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), index=True)
    engine: Mapped[str] = mapped_column(String(20), default="runner")
    event_type: Mapped[str] = mapped_column(String(30))  # workflow | tool_call | fallback
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict | None] = mapped_column(JSON)
    langfuse_trace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
