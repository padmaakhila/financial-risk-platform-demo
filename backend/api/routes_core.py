"""Auth, documents/jobs, invoices, records."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select

from backend.core.errors import NotFound
from backend.agents.audit_summarizer import summarize_audit
from backend.agents.workflow_db import make_db_tools
from backend.api.deps import CurrentUser, get_current_user, get_session, label, require
from backend.api.errors import ApiError
from backend.api.serialize import ok
from backend.api.views import invoice_detail, invoice_row, vendor_view
from backend.core.security import create_access_token, hash_password, verify_password
from backend.models import (AiOutput, BackgroundJob, Document, ExtractedField, GoodsReceipt, Invoice, PurchaseOrder, User, Vendor)
from backend.schemas.api import JobResponse, LoginRequest, TokenResponse
from backend.services.audit import append_audit_event
from backend.services.csv_import import parse_vendor_csv
from backend.services.extraction_db import register_document
from backend.services.upload_validation import resolve_stored_path, store_upload, validate_upload
from backend.workers.queue import enqueue

auth = APIRouter(prefix="/api/auth", tags=["auth"])
docs = APIRouter(prefix="/api", tags=["documents"])
invoices = APIRouter(prefix="/api", tags=["invoices"])
records = APIRouter(prefix="/api", tags=["records"])
_DUMMY_HASH = hash_password("timing-equaliser-password")


# ------------------------------------------------------------------ auth
@auth.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db=Depends(get_session)):
    st = request.app.state
    key = body.username.lower()
    if st.throttle.blocked(key):
        raise ApiError(429, "TOO_MANY_ATTEMPTS", "Too many failed sign-in attempts. Wait a few minutes and try again.")
    user = db.scalar(select(User).where(User.username == body.username))
    good = verify_password(body.password, user.password_hash if user else _DUMMY_HASH) and user is not None and user.is_active
    if not good:
        st.throttle.record_failure(key)
        append_audit_event(db, actor_id=None, actor_label=f"anonymous:{body.username[:40]}", action="LOGIN_FAILED", entity_type="user", entity_id=key[:40])
        db.commit()
        raise ApiError(401, "INVALID_CREDENTIALS", "Incorrect username or password.")  # same message for unknown user and wrong password
    st.throttle.reset(key)
    append_audit_event(db, actor_id=user.id, actor_label=f"user:{user.id}:{user.role}", action="LOGIN_SUCCESS", entity_type="user", entity_id=user.id)
    return TokenResponse(access_token=create_access_token(user.id, user.username, user.role), expires_in=st.settings.access_token_minutes * 60,
                         username=user.username, role=user.role)


@auth.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "role": user.role}


@auth.post("/logout")
def logout(request: Request, user: CurrentUser = Depends(get_current_user), db=Depends(get_session)):
    if user.jti and user.exp:
        request.app.state.revoked.revoke(user.jti, user.exp)
    append_audit_event(db, actor_id=user.id, actor_label=label(user), action="LOGOUT", entity_type="user", entity_id=user.id)
    return {"signed_out": True}


# ------------------------------------------------------------------ documents and jobs
def _job_out(j: BackgroundJob) -> dict:
    return JobResponse(job_id=j.id, status=j.status, job_type=j.job_type, progress_pct=j.progress_pct, attempts=j.attempts,
                       error=f"{j.error_class}: {j.error_message}"[:200] if j.error_class else None).model_dump()


def _visible_doc(db, user: CurrentUser, doc_id: int) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None or (user.role == "ap_clerk" and doc.uploaded_by != user.id):  # retrieval authorisation: clerks see only their own uploads
        raise NotFound("document not found")
    return doc


@docs.post("/documents", status_code=202)
def upload_document(request: Request, file: UploadFile = File(...), user: CurrentUser = Depends(require("upload")), db=Depends(get_session)):
    cfg = request.app.state.settings
    max_bytes = cfg.max_upload_mb * 1024 * 1024
    data = file.file.read(max_bytes + 1)
    v = validate_upload(file.filename or "", data, file.content_type, max_bytes=max_bytes, allowed=cfg.allowed_extensions)
    if v.extension == ".csv":
        if user.role not in ("admin", "reviewer"):
            raise ApiError(403, "FORBIDDEN", "Only reviewers and administrators can import vendor records.")
        rows, errors = parse_vendor_csv(data.decode("utf-8-sig"))
        created = skipped = 0
        for r in rows:
            if db.scalar(select(Vendor.id).where(Vendor.vendor_code == r["vendor_code"])):
                skipped += 1
                continue
            db.add(Vendor(vendor_code=r["vendor_code"], name=r["name"], tax_id=r["tax_id"], bank_account=r["bank_account"], bank_name=r["bank_name"],
                          verification_status="UNVERIFIED"))
            created += 1
        append_audit_event(db, actor_id=user.id, actor_label=label(user), action="VENDORS_IMPORTED", entity_type="vendor", entity_id="csv",
                           tool_result={"created": created, "skipped_existing": skipped, "row_errors": len(errors)})
        return ok({"imported": created, "skipped_existing": skipped, "errors": errors}, 200)
    dup = db.scalar(select(Document).where(Document.sha256 == v.sha256).limit(1))
    if dup is not None:
        return ok({"document_id": dup.id, "duplicate_upload": True, "message": "This exact file was already uploaded."}, 200)
    store_upload(cfg.upload_dir, v, data)
    doc = register_document(db, v, user.id)
    job_id = enqueue(db, "process_document", document_id=doc.id)
    return ok({"document_id": doc.id, "job_id": job_id, "status": "QUEUED"}, 202)


@docs.get("/documents")
def list_documents(limit: int = Query(30, ge=1, le=100), user: CurrentUser = Depends(require("view_evidence")), db=Depends(get_session)):
    q = select(Document).order_by(Document.id.desc()).limit(limit)
    if user.role == "ap_clerk":
        q = q.where(Document.uploaded_by == user.id)
    items = []
    for d in db.scalars(q):
        job = db.scalar(select(BackgroundJob).where(BackgroundJob.document_id == d.id).order_by(BackgroundJob.created_at.desc()).limit(1))
        inv = db.scalar(select(Invoice.id).where(Invoice.document_id == d.id).limit(1))
        items.append({"id": d.id, "filename": d.original_filename, "doc_type": d.doc_type, "kind": d.document_kind, "status": d.status, "size_bytes": d.size_bytes,
                      "created_at": d.created_at, "job": _job_out(job) if job else None, "invoice_id": inv})
    return ok({"items": items})


@docs.get("/documents/{document_id}")
def get_document(document_id: int, user: CurrentUser = Depends(require("view_evidence")), db=Depends(get_session)):
    d = _visible_doc(db, user, document_id)
    fields = [{"name": f.field_name, "value": f.value_text, "confidence": f.confidence, "method": f.confidence_method, "page": f.page_number, "snippet": f.source_snippet}
              for f in db.scalars(select(ExtractedField).where(ExtractedField.document_id == document_id).order_by(ExtractedField.id))]
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.document_id == document_id).order_by(BackgroundJob.created_at.desc()).limit(1))
    inv = db.scalar(select(Invoice.id).where(Invoice.document_id == document_id).limit(1))
    return ok({"id": d.id, "filename": d.original_filename, "mime_type": d.mime_type, "doc_type": d.doc_type, "kind": d.document_kind, "status": d.status,
               "sha256": d.sha256, "fields": fields, "job": _job_out(job) if job else None, "invoice_id": inv})


@docs.get("/documents/{document_id}/file")
def get_document_file(document_id: int, request: Request, user: CurrentUser = Depends(require("view_evidence")), db=Depends(get_session)):
    d = _visible_doc(db, user, document_id)
    path = resolve_stored_path(request.app.state.settings.upload_dir, d.stored_filename)
    if not path.is_file():
        raise NotFound("stored file is missing")
    return FileResponse(path, media_type=d.mime_type, filename=d.original_filename, content_disposition_type="inline")


@docs.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, user: CurrentUser = Depends(require("view_records")), db=Depends(get_session)):
    j = db.get(BackgroundJob, job_id)
    if j is None:
        raise NotFound("job not found")
    return _job_out(j)


# ------------------------------------------------------------------ invoices
@invoices.get("/invoices")
def list_invoices(status: str | None = None, q: str | None = None, vendor_id: int | None = None, limit: int = Query(50, ge=1, le=200),
                  offset: int = Query(0, ge=0), user: CurrentUser = Depends(require("view_records")), db=Depends(get_session)):
    cond = []
    if status:
        cond.append(Invoice.status == status)
    if vendor_id:
        cond.append(Invoice.vendor_id == vendor_id)
    if q:
        like = f"%{q.strip()[:60]}%"
        cond.append(or_(Invoice.invoice_number.ilike(like), Invoice.vendor_name_raw.ilike(like), Invoice.po_number.ilike(like)))
    total = db.scalar(select(func.count(Invoice.id)).where(*cond)) or 0
    rows = db.execute(select(Invoice, Vendor.name).join(Vendor, Vendor.id == Invoice.vendor_id, isouter=True).where(*cond).order_by(Invoice.id).limit(limit).offset(offset))
    return ok({"items": [invoice_row(i, n) for i, n in rows], "total": total, "limit": limit, "offset": offset})


@invoices.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int, user: CurrentUser = Depends(require("view_records")), db=Depends(get_session)):
    return ok(invoice_detail(db, invoice_id, user.role))


@invoices.post("/invoices/{invoice_id}/process", status_code=202)
def process_invoice(invoice_id: int, user: CurrentUser = Depends(require("process")), db=Depends(get_session)):
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise NotFound("invoice not found")
    if inv.status not in ("RECEIVED", "FAILED", "PROCESSING"):
        raise ApiError(409, "INVALID_STATE", f"Invoice is {inv.status}; only new, failed or interrupted invoices can be processed.")
    job_id = enqueue(db, "process_invoice", invoice_id=invoice_id)
    append_audit_event(db, actor_id=user.id, actor_label=label(user), action="PROCESSING_REQUESTED", entity_type="invoice", entity_id=invoice_id, tool_result={"job_id": job_id})
    return ok({"job_id": job_id, "status": "QUEUED"}, 202)


@invoices.get("/invoices/{invoice_id}/events")
def invoice_events(invoice_id: int, request: Request, user: CurrentUser = Depends(require("view_audit")), db=Depends(get_session)):
    events = make_db_tools(request.app.state.session_factory, None)["load_events"](invoice_id)
    return ok({"events": events})


@invoices.post("/invoices/{invoice_id}/audit-summary")
def audit_summary(invoice_id: int, request: Request, user: CurrentUser = Depends(require("view_audit")), db=Depends(get_session)):
    st = request.app.state
    events = make_db_tools(st.session_factory, None)["load_events"](invoice_id)
    result = summarize_audit(st.provider, events, timeout=float(st.settings.llm_timeout_seconds))
    db.add(AiOutput(invoice_id=invoice_id, kind="audit_summary", source=result.source, summary=result.summary, items=None, caveats=None,
                    verification={"problems": result.problems, "fallback_reason": result.fallback_reason}))
    return ok({"source": result.source, "label": "AI-generated summary (verified)" if result.source == "model" else "Template-generated summary (original events below are authoritative)",
               "summary": result.summary, "timeline": result.timeline, "fallback_reason": result.fallback_reason})


# ------------------------------------------------------------------ business records
@records.get("/vendors")
def list_vendors(q: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                 user: CurrentUser = Depends(require("view_records")), db=Depends(get_session)):
    cond = [or_(Vendor.name.ilike(f"%{q.strip()[:60]}%"), Vendor.vendor_code.ilike(f"%{q.strip()[:60]}%"))] if q else []
    total = db.scalar(select(func.count(Vendor.id)).where(*cond)) or 0
    items = [vendor_view(v, user.role) for v in db.scalars(select(Vendor).where(*cond).order_by(Vendor.id).limit(limit).offset(offset))]
    return ok({"items": items, "total": total})


@records.get("/purchase-orders")
def list_pos(q: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
             user: CurrentUser = Depends(require("view_records")), db=Depends(get_session)):
    cond = [PurchaseOrder.po_number.ilike(f"%{q.strip()[:40]}%")] if q else []
    total = db.scalar(select(func.count(PurchaseOrder.id)).where(*cond)) or 0
    rows = db.execute(select(PurchaseOrder, Vendor.name).join(Vendor, Vendor.id == PurchaseOrder.vendor_id).where(*cond).order_by(PurchaseOrder.id).limit(limit).offset(offset))
    return ok({"items": [{"id": p.id, "po_number": p.po_number, "vendor": n, "order_date": p.order_date, "currency": p.currency, "status": p.status, "line_count": len(p.lines)}
                         for p, n in rows], "total": total})


@records.get("/purchase-orders/{po_number}")
def get_po(po_number: str, user: CurrentUser = Depends(require("view_records")), db=Depends(get_session)):
    p = db.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == po_number))
    if p is None:
        raise NotFound("purchase order not found")
    grns = [g.grn_number for g in db.scalars(select(GoodsReceipt).where(GoodsReceipt.po_id == p.id))]
    invs = [i.invoice_number for i in db.scalars(select(Invoice).where(Invoice.po_number == po_number))]
    return ok({"po_number": p.po_number, "order_date": p.order_date, "currency": p.currency, "status": p.status, "goods_receipts": grns, "invoices": invs,
               "lines": [{"line_no": l.line_no, "description": l.description, "quantity": l.quantity, "unit_price": l.unit_price, "tax_rate": l.tax_rate} for l in p.lines]})


@records.get("/goods-receipts")
def list_grns(q: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
              user: CurrentUser = Depends(require("view_records")), db=Depends(get_session)):
    cond = [GoodsReceipt.grn_number.ilike(f"%{q.strip()[:40]}%")] if q else []
    total = db.scalar(select(func.count(GoodsReceipt.id)).where(*cond)) or 0
    rows = db.execute(select(GoodsReceipt, PurchaseOrder.po_number).join(PurchaseOrder, PurchaseOrder.id == GoodsReceipt.po_id).where(*cond)
                      .order_by(GoodsReceipt.id).limit(limit).offset(offset))
    return ok({"items": [{"id": g.id, "grn_number": g.grn_number, "po_number": po, "receipt_date": g.receipt_date,
                          "lines": [{"po_line_no": l.po_line_no, "description": l.description, "quantity_received": l.quantity_received} for l in g.lines]}
                         for g, po in rows], "total": total})
