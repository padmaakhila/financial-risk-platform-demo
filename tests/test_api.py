"""API tests (FastAPI TestClient). Cover authentication, role enforcement, the approval/payment gates, upload safety and error handling."""
import io
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import sessionmaker

from backend.agents.llm import NullProvider
from backend.core.config import Settings
from backend.core.security import create_access_token
from backend.database.session import make_engine, session_scope
from backend.integrations.clients import ErpClient, VendorVerificationClient
from backend.integrations.erp_mock_core import ErpMock
from backend.integrations.mock_server import start_in_thread
from backend.integrations.vendor_mock_core import VendorMock
from backend.main import create_app
from backend.models import AuditEvent, BackgroundJob, Base, Document, IntegrationRecord, Invoice, Setting
from scripts.generate_data import DEMO_USERS, build_dataset
from scripts.generate_documents import write_digital_pdf
from backend.services.doc_text import invoice_lines_text
from scripts.seed_database import seed

DS = build_dataset(42)
PASSWORDS = {u: p for u, _, p in DEMO_USERS}
CLEAN = [i["invoice_number"] for i in DS["invoices"] if i["scenario_code"] == "S01_CLEAN"]
NOSLEEP = lambda s: None


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("api")
    engine = make_engine(f"sqlite:///{(tmp / 'api.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_scope(factory) as s:
        seed(s, DS)
        s.add(Setting(key="price_tolerance_pct", value="1.00", description="x"))
    erp_core, vendor_core = ErpMock(timeout_delay=1.0), VendorMock.from_dataset(DS)
    erp_srv, erp_url = start_in_thread(erp_core)
    ven_srv, ven_url = start_in_thread(vendor_core)
    settings = Settings(upload_dir=tmp / "uploads", max_upload_mb=1)
    app = create_app(settings, factory, ErpClient(erp_url, timeout=0.5, sleep=NOSLEEP), VendorVerificationClient(ven_url, timeout=0.5, sleep=NOSLEEP), NullProvider())
    yield {"client": TestClient(app, raise_server_exceptions=False), "factory": factory, "erp": erp_core, "settings": settings, "tmp": tmp}
    erp_srv.shutdown()
    ven_srv.shutdown()


class Api:
    def __init__(self, stack):
        self.c, self.f, self.erp, self.stack = stack["client"], stack["factory"], stack["erp"], stack
        self._n = 0
        self._tokens = {}

    def h(self, who):
        if who not in self._tokens:
            r = self.c.post("/api/auth/login", json={"username": who, "password": PASSWORDS[who]})
            assert r.status_code == 200, r.text
            self._tokens[who] = {"Authorization": f"Bearer {r.json()['access_token']}"}
        return self._tokens[who]

    def invoice(self, status="AWAITING_REVIEW"):
        self._n += 1
        with session_scope(self.f) as s:
            inv = s.scalar(select(Invoice).where(Invoice.invoice_number == CLEAN[self._n + 40], Invoice.status == "RECEIVED"))
            inv.status = status
            return inv.id

    def audit_count(self, action):
        with session_scope(self.f) as s:
            return s.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.action == action))


@pytest.fixture(scope="module")
def api(stack):
    return Api(stack)


def pdf_bytes(tmp, name="inv.pdf", invoice=None):
    p = tmp / name
    write_digital_pdf(p, invoice_lines_text(invoice or DS["invoices"][3]))
    return p.read_bytes()


# ---------------------------------------------------------------- authentication
def test_every_ground_truth_unauthorized_request_gets_401(api):
    for t in DS["ground_truth"]:
        if t["scenario_code"] != "S23_UNAUTHORIZED_API":
            continue
        req = t["expected"]["request"]
        body = {"decision": "approve", "idempotency_key": "k"} if req["path"].endswith("decision") else ({"values": {"price_tolerance_pct": "1"}} if req["method"] == "PUT" else None)
        r = api.c.request(req["method"], req["path"], json=body)
        assert r.status_code == t["expected"]["no_token_status"] == 401, req
        assert r.json()["error"]["code"] == "NOT_AUTHENTICATED" and r.json()["error"]["request_id"]


def test_garbage_and_expired_tokens_are_rejected(api):
    assert api.c.get("/api/invoices", headers={"Authorization": "Bearer not.a.token"}).json()["error"]["code"] == "INVALID_TOKEN"
    expired = create_access_token(1, "admin", "admin", minutes=-1)
    assert api.c.get("/api/invoices", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_login_errors_are_generic_and_repeated_failures_lock_the_account(api):
    wrong = api.c.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
    ghost = api.c.post("/api/auth/login", json={"username": "ghost-user", "password": "wrong-password"})
    assert wrong.status_code == ghost.status_code == 401 and wrong.json()["error"]["message"] == ghost.json()["error"]["message"]
    for _ in range(5):
        api.c.post("/api/auth/login", json={"username": "lock-me", "password": "x"})
    assert api.c.post("/api/auth/login", json={"username": "lock-me", "password": "x"}).status_code == 429
    assert api.audit_count("LOGIN_FAILED") >= 7


def test_logout_revokes_the_token(api):
    r = api.c.post("/api/auth/login", json={"username": "auditor", "password": PASSWORDS["auditor"]})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert api.c.get("/api/auth/me", headers=h).json()["role"] == "auditor"
    assert api.c.post("/api/auth/logout", headers=h).status_code == 200
    assert api.c.get("/api/auth/me", headers=h).status_code == 401


# ---------------------------------------------------------------- authorization
def test_roles_are_enforced_on_the_backend_and_denials_are_audited(api):
    before = api.audit_count("ACCESS_DENIED")
    inv = api.invoice()
    body = {"decision": "approve", "idempotency_key": "x-1"}
    assert api.c.post(f"/api/invoices/{inv}/decision", json=body, headers=api.h("clerk")).status_code == 403
    assert api.c.post(f"/api/invoices/{inv}/decision", json=body, headers=api.h("auditor")).status_code == 403
    assert api.c.get("/api/review/queue", headers=api.h("clerk")).status_code == 403
    assert api.c.get("/api/admin/users", headers=api.h("auditor")).status_code == 403
    assert api.c.get("/api/admin/settings", headers=api.h("reviewer")).status_code == 403
    assert api.c.post(f"/api/invoices/{inv}/payment", headers=api.h("clerk")).status_code == 403
    assert api.c.post("/api/documents", files={"file": ("a.pdf", b"x", "application/pdf")}, headers=api.h("auditor")).status_code == 403
    assert api.audit_count("ACCESS_DENIED") >= before + 7
    with session_scope(api.f) as s:
        assert s.get(Invoice, inv).status == "AWAITING_REVIEW"


# ---------------------------------------------------------------- approval and payment gates
def test_payment_requires_recorded_approval_then_succeeds_once(api):
    inv = api.invoice()
    h = api.h("reviewer")
    blocked = api.c.post(f"/api/invoices/{inv}/payment", headers=h)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "APPROVAL_REQUIRED"
    d = api.c.post(f"/api/invoices/{inv}/decision", json={"decision": "approve", "idempotency_key": f"k-{inv}"}, headers=h)
    assert d.status_code == 200 and d.json()["invoice_status"] == "APPROVED"
    again = api.c.post(f"/api/invoices/{inv}/decision", json={"decision": "approve", "idempotency_key": f"k-{inv}"}, headers=h)
    assert again.json()["review_id"] == d.json()["review_id"]
    other = api.c.post(f"/api/invoices/{inv}/decision", json={"decision": "reject", "comment": "second thoughts", "idempotency_key": f"k2-{inv}"}, headers=h)
    assert other.status_code == 409 and other.json()["error"]["code"] == "INVALID_STATE"
    paid = api.c.post(f"/api/invoices/{inv}/payment", headers=h)
    replay = api.c.post(f"/api/invoices/{inv}/payment", headers=h)
    assert paid.status_code == 200 and paid.json()["status"] == "PAID" and replay.json()["replayed"] and paid.json()["payment_id"] == replay.json()["payment_id"]
    assert sum(1 for p in api.erp.payments.values() if p["approval_id"] == str(d.json()["review_id"])) == 1


def test_erp_outage_gives_202_and_never_marks_paid(api):
    inv = api.invoice()
    h = api.h("reviewer")
    api.c.post(f"/api/invoices/{inv}/decision", json={"decision": "approve", "idempotency_key": f"o-{inv}"}, headers=h)
    api.erp.handle("POST", "/admin/simulate", {}, {"mode": "down"})
    try:
        r = api.c.post(f"/api/invoices/{inv}/payment", headers=h)
    finally:
        api.erp.handle("POST", "/admin/simulate", {}, {"mode": "normal"})
    assert r.status_code == 202 and r.json()["status"] == "PAYMENT_PENDING" and r.json()["retry"]
    assert api.c.get(f"/api/invoices/{inv}", headers=h).json()["invoice"]["status"] == "PAYMENT_PENDING"
    assert api.c.post(f"/api/invoices/{inv}/payment", headers=h).json()["status"] == "PAID"


def test_rejected_invoice_can_never_be_paid(api):
    inv = api.invoice()
    h = api.h("reviewer")
    assert api.c.post(f"/api/invoices/{inv}/decision", json={"decision": "reject", "comment": "duplicate of another invoice", "idempotency_key": f"r-{inv}"}, headers=h).status_code == 200
    assert api.c.post(f"/api/invoices/{inv}/payment", headers=h).json()["error"]["code"] == "APPROVAL_REQUIRED"


def test_validation_errors_use_the_envelope_and_never_echo_input(api):
    inv = api.invoice()
    r = api.c.post(f"/api/invoices/{inv}/decision", json={"decision": "SECRET-EVIL-VALUE", "idempotency_key": "k"}, headers=api.h("reviewer"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REQUEST" and "SECRET-EVIL-VALUE" not in r.text
    r = api.c.post(f"/api/invoices/{inv}/decision", json={"decision": "reject", "idempotency_key": "kk"}, headers=api.h("reviewer"))
    assert r.json()["error"]["code"] == "VALIDATION_FAILED"
    assert api.c.get("/api/invoices/99999999", headers=api.h("reviewer")).json()["error"]["code"] == "NOT_FOUND"


# ---------------------------------------------------------------- uploads
def test_upload_rejects_bad_files_with_clear_errors(api):
    h = api.h("clerk")
    for name, data, mime, status, code in [("run.exe", b"MZ\x90\x00", "application/octet-stream", 415, "UNSUPPORTED_FILE_TYPE"),
                                           ("fake.pdf", b"MZ\x90\x00 not pdf", "application/pdf", 415, "SIGNATURE_MISMATCH"),
                                           ("empty.pdf", b"", "application/pdf", 400, "EMPTY_FILE"),
                                           ("trunc.pdf", b"%PDF-1.4\n" + b"x" * 3000, "application/pdf", 422, "MALFORMED_FILE"),
                                           ("big.pdf", b"%PDF-1.4\n" + b"x" * (2 * 1024 * 1024) + b"\n%%EOF", "application/pdf", 413, "FILE_TOO_LARGE"),
                                           ("../../evil.pdf", b"%PDF-1.4\n%%EOF\n", "image/png", 415, "MIME_MISMATCH")]:
        r = api.c.post("/api/documents", files={"file": (name, data, mime)}, headers=h)
        assert (r.status_code, r.json()["error"]["code"]) == (status, code), name


def test_valid_upload_is_stored_safely_queued_and_deduplicated(api, stack):
    h = api.h("clerk")
    data = pdf_bytes(stack["tmp"], invoice=DS["invoices"][5])
    r = api.c.post("/api/documents", files={"file": ("../../my invoice.pdf", data, "application/pdf")}, headers=h)
    assert r.status_code == 202 and r.json()["status"] == "QUEUED"
    doc_id, job_id = r.json()["document_id"], r.json()["job_id"]
    stored = list((stack["settings"].upload_dir).iterdir())
    assert stored and all(p.parent == stack["settings"].upload_dir and len(p.stem) == 32 for p in stored)
    with session_scope(api.f) as s:
        assert s.get(BackgroundJob, job_id).status == "QUEUED" and s.get(Document, doc_id).original_filename == "my invoice.pdf"
    assert api.c.get(f"/api/jobs/{job_id}", headers=h).json()["status"] == "QUEUED"
    dup = api.c.post("/api/documents", files={"file": ("again.pdf", data, "application/pdf")}, headers=h)
    assert dup.status_code == 200 and dup.json()["duplicate_upload"] and dup.json()["document_id"] == doc_id
    assert api.c.get(f"/api/documents/{doc_id}/file", headers=h).content == data


def test_clerks_cannot_read_other_users_documents(api, stack):
    data = pdf_bytes(stack["tmp"], invoice=DS["invoices"][7])
    rev = api.c.post("/api/documents", files={"file": ("rev.pdf", data, "application/pdf")}, headers=api.h("reviewer"))
    doc_id = rev.json()["document_id"]
    assert api.c.get(f"/api/documents/{doc_id}", headers=api.h("clerk")).status_code == 404
    assert api.c.get(f"/api/documents/{doc_id}/file", headers=api.h("clerk")).status_code == 404
    assert api.c.get(f"/api/documents/{doc_id}", headers=api.h("auditor")).status_code == 200
    assert doc_id not in [d["id"] for d in api.c.get("/api/documents", headers=api.h("clerk")).json()["items"]]


def test_vendor_csv_import_is_restricted_and_validated(api):
    csv_bytes = b"vendor_code,name,tax_id,bank_account,bank_name\nV7001,Import Co,TX111111111,,\nV7002,Bad,TX1,,\n"
    assert api.c.post("/api/documents", files={"file": ("v.csv", csv_bytes, "text/csv")}, headers=api.h("clerk")).status_code == 403
    r = api.c.post("/api/documents", files={"file": ("v.csv", csv_bytes, "text/csv")}, headers=api.h("reviewer"))
    assert r.status_code == 200 and r.json()["imported"] == 1 and len(r.json()["errors"]) == 1
    assert api.c.get("/api/vendors?q=Import", headers=api.h("reviewer")).json()["total"] == 1


# ---------------------------------------------------------------- data views
def test_bank_details_are_masked_for_clerks_but_not_reviewers(api):
    inv = api.invoice("RECEIVED")
    clerk = api.c.get(f"/api/invoices/{inv}", headers=api.h("clerk")).json()["invoice"]["bank_account"]
    full = api.c.get(f"/api/invoices/{inv}", headers=api.h("reviewer")).json()["invoice"]["bank_account"]
    assert clerk.startswith("*") and clerk[-4:] == full[-4:] and full.startswith("FB")
    vendors = api.c.get("/api/vendors", headers=api.h("clerk")).json()["items"]
    assert all(v["bank_account"] is None or v["bank_account"].startswith("*") for v in vendors)


def test_money_is_returned_as_exact_strings(api):
    inv = api.c.get("/api/invoices?limit=1", headers=api.h("clerk")).json()["items"][0]
    assert isinstance(inv["grand_total"], str) and "." in inv["grand_total"]


def test_reports_agree_with_the_database(api):
    r = api.c.get("/api/reports/reconciliation", headers=api.h("auditor")).json()
    with session_scope(api.f) as s:
        assert r["totals"]["invoice_count"] == s.scalar(select(func.count(Invoice.id))) == len(r["rows"])
    csv_resp = api.c.get("/api/reports/reconciliation.csv", headers=api.h("auditor"))
    assert csv_resp.headers["content-type"].startswith("text/csv") and "attachment" in csv_resp.headers["content-disposition"]
    assert csv_resp.text.count("\n") >= len(r["rows"]) + 2
    assert api.c.get("/api/reports/reconciliation.pdf", headers=api.h("auditor")).content.startswith(b"%PDF")
    s = api.c.get("/api/reports/summary", headers=api.h("auditor")).json()
    assert s["invoices_total"] == r["totals"]["invoice_count"] and sum(s["invoices_by_status"].values()) == s["invoices_total"]


# ---------------------------------------------------------------- administration
def test_settings_are_validated_and_changes_audited(api):
    h = api.h("admin")
    assert api.c.put("/api/admin/settings", json={"values": {"price_tolerance_pct": "-1"}}, headers=h).status_code == 422
    assert api.c.put("/api/admin/settings", json={"values": {"nonsense": "1"}}, headers=h).status_code == 422
    assert api.c.put("/api/admin/settings", json={"values": {"price_tolerance_pct": "2.50"}}, headers=h).json()["updated"]["price_tolerance_pct"]["new"] == "2.50"
    assert api.audit_count("SETTINGS_CHANGED") >= 1


def test_user_management_rules(api):
    h = api.h("admin")
    assert api.c.post("/api/admin/users", json={"username": "newbie", "password": "short1", "role": "ap_clerk"}, headers=h).status_code == 422
    assert api.c.post("/api/admin/users", json={"username": "newbie", "password": "longpassword12", "role": "ap_clerk"}, headers=h).status_code == 201
    assert api.c.post("/api/admin/users", json={"username": "newbie", "password": "longpassword12", "role": "ap_clerk"}, headers=h).status_code == 409
    me = api.c.get("/api/auth/me", headers=h).json()["id"]
    assert api.c.patch(f"/api/admin/users/{me}", json={"role": "auditor"}, headers=h).status_code == 409
    assert api.c.post("/api/auth/login", json={"username": "newbie", "password": "longpassword12"}).status_code == 200


def test_integration_health_and_simulation(api):
    h = api.h("admin")
    health = api.c.get("/api/admin/integrations", headers=h).json()
    assert health["database"]["healthy"] and health["erp_mock"]["healthy"] and health["llm"]["available"] is False
    assert api.c.post("/api/admin/integrations/erp/simulate", json={"mode": "down"}, headers=h).status_code == 200
    assert api.c.get("/api/admin/integrations", headers=h).json()["erp_mock"]["healthy"] is False
    api.c.post("/api/admin/integrations/erp/simulate", json={"mode": "normal"}, headers=h)
    assert api.c.post("/api/admin/integrations/other/simulate", json={"mode": "down"}, headers=h).status_code == 404


def test_monitoring_audit_and_health_endpoints(api):
    m = api.c.get("/api/monitoring/metrics", headers=api.h("auditor")).json()
    assert {"jobs", "ai", "api", "failures"} <= set(m) and m["integrations"] is None
    assert api.c.get("/api/monitoring/metrics", headers=api.h("clerk")).status_code == 403
    assert api.c.get("/api/audit/verify", headers=api.h("auditor")).json()["chain_ok"] is True
    h = api.c.get("/api/health")
    assert h.status_code == 200 and h.json()["database"] == "ok" and h.headers["x-request-id"] and h.headers["x-content-type-options"] == "nosniff"


def test_openapi_describes_secured_endpoints(api):
    spec = api.c.get("/openapi.json").json()
    assert "/api/invoices/{invoice_id}/decision" in spec["paths"] and "/api/documents" in spec["paths"]
    assert "HTTPBearer" in spec["components"]["securitySchemes"]


def test_unexpected_bugs_are_500_not_disguised_as_404(api, stack):
    from fastapi import APIRouter
    router = APIRouter()

    @router.get("/api/_boom_key")
    def boom():
        return {}["missing"]  # a KeyError is a LookupError, but it is a bug, not a missing record

    stack["client"].app.include_router(router)
    r = stack["client"].get("/api/_boom_key")
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR" and "missing" not in r.text
