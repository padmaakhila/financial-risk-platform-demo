"""Review queue, decisions, payments, reports, admin, monitoring, health."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text

from backend.core.errors import NotFound
from backend.api.deps import CurrentUser, get_session, label, require
from backend.api.errors import ApiError
from backend.api.serialize import ok
from backend.api.views import invoice_row
from backend.core.constants import DEFAULT_SETTINGS
from backend.core.http import HttpError, http_json
from backend.core.metrics import job_stats, llm_stats
from backend.core.security import hash_password
from backend.models import AiOutput, AuditEvent, BackgroundJob, ExceptionRecord, Invoice, LlmUsage, Setting, User, Vendor, utcnow
from backend.schemas.api import DecisionRequest, DecisionResponse, PaymentResponse, SettingsUpdate, SimulateRequest, UserCreate, UserUpdate
from backend.services.audit import append_audit_event, verify_audit_chain
from backend.services.dashboard import dashboard_summary, job_rows
from backend.services.payments import pay_invoice
from backend.services.reports import SEV, build_totals, fetch_reconciliation_rows, render_csv, render_pdf
from backend.services.review import record_decision

review = APIRouter(prefix="/api", tags=["review"])
reports = APIRouter(prefix="/api/reports", tags=["reports"])
admin = APIRouter(prefix="/api/admin", tags=["admin"])
monitoring = APIRouter(prefix="/api", tags=["monitoring"])
health = APIRouter(prefix="/api", tags=["health"])


# ------------------------------------------------------------------ review + payment
@review.get("/review/queue")
def review_queue(limit: int = Query(50, ge=1, le=200), user: CurrentUser = Depends(require("view_queue")), db=Depends(get_session)):
    items = []
    rows = db.execute(select(Invoice, Vendor.name).join(Vendor, Vendor.id == Invoice.vendor_id, isouter=True).where(Invoice.status == "AWAITING_REVIEW")
                      .order_by(Invoice.created_at, Invoice.id).limit(limit))
    for inv, vname in rows:
        sevs = [s for (s,) in db.execute(select(ExceptionRecord.severity).where(ExceptionRecord.invoice_id == inv.id, ExceptionRecord.status == "OPEN"))]
        ai = db.scalar(select(AiOutput.source).where(AiOutput.invoice_id == inv.id, AiOutput.kind == "risk_explanation").order_by(AiOutput.id.desc()).limit(1))
        items.append({**invoice_row(inv, vname), "open_exceptions": len(sevs), "highest_severity": max(sevs, key=SEV.index) if sevs else None, "explanation_source": ai})
    return ok({"items": items, "total": len(items)})


@review.post("/invoices/{invoice_id}/decision", response_model=DecisionResponse)
def decide(invoice_id: int, body: DecisionRequest, user: CurrentUser = Depends(require("decide")), db=Depends(get_session)):
    r = record_decision(db, invoice_id=invoice_id, reviewer_id=user.id, reviewer_role=user.role, decision=body.decision, comment=body.comment,
                        idempotency_key=body.idempotency_key)
    db.expire_all()  # the status was changed with a guarded UPDATE; reload it
    return DecisionResponse(review_id=r.id, invoice_id=invoice_id, decision=r.decision, invoice_status=db.get(Invoice, invoice_id).status)


@review.post("/invoices/{invoice_id}/payment", response_model=PaymentResponse)
def pay(invoice_id: int, request: Request, user: CurrentUser = Depends(require("pay"))):
    st = request.app.state
    result = pay_invoice(st.session_factory, st.erp_client, invoice_id=invoice_id, actor_id=user.id, actor_role=user.role)
    return JSONResponse(result, status_code=200 if result["status"] == "PAID" else 202)


# ------------------------------------------------------------------ reports
@reports.get("/summary")
def summary(user: CurrentUser = Depends(require("view_reports")), db=Depends(get_session)):
    return ok(dashboard_summary(db))


@reports.get("/reconciliation")
def reconciliation(status: str | None = None, user: CurrentUser = Depends(require("view_reports")), db=Depends(get_session)):
    rows = fetch_reconciliation_rows(db, status)
    return ok({"rows": rows, "totals": build_totals(rows)})


def _export(kind: str, status: str | None, user: CurrentUser, db) -> Response:
    rows = fetch_reconciliation_rows(db, status)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    append_audit_event(db, actor_id=user.id, actor_label=label(user), action="REPORT_EXPORTED", entity_type="report", entity_id=kind,
                       tool_result={"rows": len(rows), "status_filter": status})
    if kind == "csv":
        body, mime = render_csv(rows).encode("utf-8"), "text/csv; charset=utf-8"
    else:
        body, mime = render_pdf(rows, generated=stamp), "application/pdf"
    return Response(body, media_type=mime, headers={"Content-Disposition": f'attachment; filename="reconciliation-{stamp}.{kind}"'})


@reports.get("/reconciliation.csv")
def reconciliation_csv(status: str | None = None, user: CurrentUser = Depends(require("view_reports")), db=Depends(get_session)):
    return _export("csv", status, user, db)


@reports.get("/reconciliation.pdf")
def reconciliation_pdf(status: str | None = None, user: CurrentUser = Depends(require("view_reports")), db=Depends(get_session)):
    return _export("pdf", status, user, db)


# ------------------------------------------------------------------ admin
@admin.get("/users")
def list_users(user: CurrentUser = Depends(require("admin")), db=Depends(get_session)):
    return ok({"items": [{"id": u.id, "username": u.username, "role": u.role, "is_active": u.is_active, "created_at": u.created_at} for u in db.scalars(select(User).order_by(User.id))]})


@admin.post("/users", status_code=201)
def create_user(body: UserCreate, user: CurrentUser = Depends(require("admin")), db=Depends(get_session)):
    if db.scalar(select(User.id).where(User.username == body.username)):
        raise ApiError(409, "CONFLICT", "That username already exists.")
    u = User(username=body.username, role=body.role, password_hash=hash_password(body.password))
    db.add(u)
    db.flush()
    append_audit_event(db, actor_id=user.id, actor_label=label(user), action="USER_CREATED", entity_type="user", entity_id=u.id, details={"username": u.username, "role": u.role})
    return ok({"id": u.id, "username": u.username, "role": u.role}, 201)


@admin.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, user: CurrentUser = Depends(require("admin")), db=Depends(get_session)):
    u = db.get(User, user_id)
    if u is None:
        raise NotFound("user not found")
    admins = db.scalar(select(func.count(User.id)).where(User.role == "admin", User.is_active.is_(True))) or 0
    losing_admin = u.role == "admin" and u.is_active and ((body.role and body.role != "admin") or body.is_active is False)
    if losing_admin and (admins <= 1 or u.id == user.id):
        raise ApiError(409, "CONFLICT", "You cannot remove the last active administrator or demote yourself.")
    changes = {}
    if body.role:
        changes["role"], u.role = body.role, body.role
    if body.is_active is not None:
        changes["is_active"], u.is_active = body.is_active, body.is_active
    if body.password:
        u.password_hash = hash_password(body.password)
        changes["password"] = "changed"
    append_audit_event(db, actor_id=user.id, actor_label=label(user), action="USER_UPDATED", entity_type="user", entity_id=u.id, details=changes)
    return ok({"id": u.id, "username": u.username, "role": u.role, "is_active": u.is_active})


RANGES = {"price_tolerance_pct": ("0", "100"), "qty_tolerance_pct": ("0", "100"), "amount_tolerance_abs": ("0", "1000"), "duplicate_threshold": ("0.5", "1"),
          "low_confidence_threshold": ("0", "1"), "max_verification_retries": ("0", "5"), "llm_timeout_seconds": ("1", "300")}


@admin.get("/settings")
def get_settings_endpoint(user: CurrentUser = Depends(require("admin")), db=Depends(get_session)):
    return ok({"items": [{"key": s.key, "value": s.value, "description": s.description, "updated_at": s.updated_at} for s in db.scalars(select(Setting).order_by(Setting.key))]})


@admin.put("/settings")
def put_settings(body: SettingsUpdate, user: CurrentUser = Depends(require("admin")), db=Depends(get_session)):
    unknown = [k for k in body.values if k not in DEFAULT_SETTINGS]
    if unknown:
        raise ApiError(422, "VALIDATION_FAILED", f"Unknown setting(s): {unknown}")
    changes = {}
    for key, raw in body.values.items():
        try:
            val = Decimal(raw)
        except InvalidOperation:
            raise ApiError(422, "VALIDATION_FAILED", f"{key} must be a number.") from None
        lo, hi = map(Decimal, RANGES[key])
        if not val.is_finite() or not lo <= val <= hi:
            raise ApiError(422, "VALIDATION_FAILED", f"{key} must be between {lo} and {hi}.")
        row = db.get(Setting, key)
        if row is None:
            row = Setting(key=key, value=raw, description=DEFAULT_SETTINGS[key][1])
            db.add(row)
            changes[key] = {"old": None, "new": raw}
        elif row.value != raw:
            changes[key] = {"old": row.value, "new": raw}
            row.value, row.updated_by = raw, user.id
    append_audit_event(db, actor_id=user.id, actor_label=label(user), action="SETTINGS_CHANGED", entity_type="settings", entity_id="matching", details=changes)
    return ok({"updated": changes})


def integration_health(request: Request) -> dict:
    st = request.app.state
    from backend.services.extraction import TesseractEngine
    try:
        with st.session_factory() as s:
            s.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"database": {"healthy": db_ok}, "erp_mock": {"healthy": st.erp_client.healthy(), "url": st.erp_client.base_url},
            "vendor_verification_mock": {"healthy": st.vendor_client.healthy(), "url": st.vendor_client.base_url},
            "llm": {"provider": st.provider.name, "model": getattr(st.provider, "model", None), "available": st.provider.is_available()},
            "ocr": {"tesseract_available": TesseractEngine(st.settings.tesseract_cmd).available()}}


@admin.get("/integrations")
def integrations(request: Request, user: CurrentUser = Depends(require("admin"))):
    return ok(integration_health(request))


@admin.post("/integrations/{name}/simulate")
def simulate(name: str, body: SimulateRequest, request: Request, user: CurrentUser = Depends(require("admin")), db=Depends(get_session)):
    st = request.app.state
    client = {"erp": st.erp_client, "vendor": st.vendor_client}.get(name)
    if client is None:
        raise ApiError(404, "NOT_FOUND", "Unknown integration. Use 'erp' or 'vendor'.")
    if name == "erp" and body.mode == "reject_all":
        raise ApiError(422, "VALIDATION_FAILED", "reject_all only applies to the vendor service.")
    try:
        http_json("POST", f"{client.base_url}/admin/simulate", {"mode": body.mode, "fail_n": body.fail_n}, timeout=3)
    except HttpError:
        raise ApiError(502, "INTEGRATION_UNAVAILABLE", "The mock service is not reachable, so its mode could not be changed.") from None
    append_audit_event(db, actor_id=user.id, actor_label=label(user), action="SIMULATION_MODE_SET", entity_type="integration", entity_id=name, details=body.model_dump())
    return ok({"integration": name, "mode": body.mode})


# ------------------------------------------------------------------ monitoring + audit
@monitoring.get("/monitoring/metrics")
def metrics(request: Request, user: CurrentUser = Depends(require("monitoring")), db=Depends(get_session)):
    failed = db.scalars(select(BackgroundJob).where(BackgroundJob.status.in_(("FAILED", "RETRYING"))).order_by(BackgroundJob.created_at.desc()).limit(15))
    usage = [{"source": u.source, "outcome": u.outcome, "prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens, "cost_usd": u.cost_usd,
              "latency_ms": u.latency_ms} for u in db.scalars(select(LlmUsage))]
    return ok({"jobs": job_stats(job_rows(db)), "ai": llm_stats(usage), "api": request.app.state.req_metrics.summary(),
               "failures": [{"job_id": j.id, "type": j.job_type, "status": j.status, "error_class": j.error_class, "message": (j.error_message or "")[:160],
                             "attempts": j.attempts, "invoice_id": j.invoice_id} for j in failed],
               "integrations": integration_health(request) if user.role in ("admin", "reviewer") else None})


@monitoring.get("/audit/verify")
def audit_verify(user: CurrentUser = Depends(require("view_audit")), db=Depends(get_session)):
    good, bad_id = verify_audit_chain(db)
    return ok({"chain_ok": good, "first_bad_event_id": bad_id, "events": db.scalar(select(func.count(AuditEvent.id))),
               "note": "Hash chain detects edits; it is tamper-evident, not immutable."})


@monitoring.get("/audit/events")
def audit_events(entity_type: str | None = None, entity_id: str | None = None, limit: int = Query(100, ge=1, le=500),
                 user: CurrentUser = Depends(require("view_audit")), db=Depends(get_session)):
    q = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
    if entity_type:
        q = q.where(AuditEvent.entity_type == entity_type)
    if entity_id:
        q = q.where(AuditEvent.entity_id == entity_id)
    return ok({"items": [{"id": e.id, "created_at": e.created_at, "actor": e.actor_label, "action": e.action, "entity_type": e.entity_type, "entity_id": e.entity_id,
                          "decision": e.decision, "tool_result": e.tool_result} for e in db.scalars(q)]})


@health.get("/health")
def health_check(request: Request):
    try:
        with request.app.state.session_factory() as s:
            s.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok", "time": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    except Exception:
        return JSONResponse({"status": "degraded", "database": "unavailable"}, status_code=503)
