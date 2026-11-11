"""Executes every Streamlit page script against a stub `streamlit` and a fake API that follows the real contract.
This is NOT a browser test; it checks that page code runs, calls the API correctly and shows the right messages."""
import http.server
import json
import pathlib
import runpy
import threading
import types

import sys

from tests import fake_streamlit as fs

st = fs.install()
try:
    import plotly.express  # noqa: F401
except ImportError:  # sandbox without plotly: a stub keeps page code runnable
    _px = types.ModuleType("plotly.express")
    _px.bar = lambda *a, **k: fs.Any()
    sys.modules["plotly"], sys.modules["plotly.express"] = types.ModuleType("plotly"), _px
    sys.modules["plotly"].express = _px
import ui.state  # noqa: E402  (must come after the stub is installed)
from tests import fake_api  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRV, URL = fake_api.start()
ui.state.base_url = lambda: URL
PAGES = {"login": "pages/1_Login.py", "dashboard": "pages/2_Dashboard.py", "upload": "pages/3_Document_Upload.py", "records": "pages/4_Business_Records.py",
         "workflow": "pages/5_Agent_Workflow.py", "review": "pages/6_Review_Queue.py", "reports": "pages/7_Reports.py", "admin": "pages/8_Administration.py",
         "monitoring": "pages/9_Monitoring.py"}


class UploadedFile:
    def __init__(self, name="inv.pdf", data=None, ctype="application/pdf"):
        self.name, self.type, self._data = name, ctype, fake_api.PDF if data is None else data

    def getvalue(self):
        return self._data


def run(path, role="reviewer", logged_in=True, clicks=(), text=None, select=None, checks=None, file=None, session=None):
    fs.CFG.reset()
    st.session_state.clear()
    if logged_in:
        st.session_state.update(token="tok", user={"username": role, "role": role})
    st.session_state.update(session or {})
    fs.CFG.clicks, fs.CFG.text, fs.CFG.select, fs.CFG.checks, fs.CFG.file = set(clicks), text or {}, select or {}, checks or {}, file
    fake_api.CALLS.clear()
    stopped = None
    try:
        runpy.run_path(str(ROOT / path), run_name="__main__")
    except (fs.StopPage, fs.RerunPage) as e:
        stopped = type(e).__name__
    return types.SimpleNamespace(log=list(fs.CFG.log), calls=list(fake_api.CALLS), stopped=stopped, session=dict(st.session_state), downloads=list(fs.CFG.downloads),
                                 pages=list(fs.CFG.pages))


def msgs(r, kind):
    return [t for k, t in r.log if k == kind]


def posted(r, method, fragment):
    return [c for c in r.calls if c["method"] == method and fragment in c["path"]]


# ---------------------------------------------------------------- every page runs cleanly
def test_every_page_renders_for_an_admin_without_errors():
    for name, path in PAGES.items():
        r = run(path, role="admin")
        assert not msgs(r, "error"), (name, msgs(r, "error"))


def test_pages_refuse_users_who_are_not_signed_in():
    for name, path in PAGES.items():
        if name == "login":
            continue
        r = run(path, logged_in=False)
        assert r.stopped == "StopPage" and any("sign in" in w.lower() for w in msgs(r, "warning")) and not r.calls, name


def test_pages_hide_content_from_roles_without_permission():
    for name, role in [("review", "ap_clerk"), ("review", "auditor"), ("admin", "reviewer"), ("admin", "auditor"), ("upload", "auditor"), ("monitoring", "ap_clerk")]:
        r = run(PAGES[name], role=role)
        assert r.stopped == "StopPage" and any("cannot open this page" in e for e in msgs(r, "error")) and not r.calls, (name, role)


def test_read_only_roles_can_open_their_pages():
    for name, role in [("dashboard", "auditor"), ("records", "auditor"), ("reports", "auditor"), ("monitoring", "auditor"), ("workflow", "ap_clerk"), ("upload", "ap_clerk"), ("records", "ap_clerk")]:
        r = run(PAGES[name], role=role)
        assert not msgs(r, "error") and r.calls, (name, role, msgs(r, "error"))


# ---------------------------------------------------------------- navigation
def test_navigation_is_role_aware():
    titles = lambda r: [p.title for p in r.pages]
    out = run("app.py", logged_in=False)
    assert titles(out) == ["Sign in"] and out.pages[0].default is True
    aud = run("app.py", role="auditor")
    assert titles(aud) == ["Account", "Dashboard", "Business Records", "AI / Agent Workflow", "Reports", "Monitoring"] and aud.pages[0].default is False and aud.pages[1].default
    clerk = run("app.py", role="ap_clerk")
    assert "Document Upload" in titles(clerk) and "Review & Approval" not in titles(clerk) and "Administration" not in titles(clerk)
    rev = run("app.py", role="reviewer")
    assert "Review & Approval" in titles(rev) and "Administration" not in titles(rev)
    assert [p.title for p in run("app.py", role="admin").pages][-2:] == ["Administration", "Monitoring"]


# ---------------------------------------------------------------- login
def test_login_signs_in_with_the_api_and_stores_only_ui_state():
    r = run(PAGES["login"], logged_in=False, clicks={"Sign in"}, text={"Username": "alice", "Password": "pw"})
    assert r.stopped == "RerunPage" and r.session["token"] == "tok" and r.session["user"] == {"username": "alice", "role": "reviewer"}
    assert posted(r, "POST", "/api/auth/login")[0]["auth"] is None and set(r.session) == {"token", "user"}


def test_login_validates_empty_fields_before_calling_the_api():
    r = run(PAGES["login"], logged_in=False, clicks={"Sign in"}, text={"Username": "  ", "Password": ""})
    assert any("Enter both" in e for e in msgs(r, "error")) and not r.calls


# ---------------------------------------------------------------- review and payment
CONFIRM = "I reviewed the evidence and understand this decision is recorded in the audit trail."


def test_decision_requires_confirmation_then_posts_with_an_idempotency_key():
    r = run(PAGES["review"], clicks={"Record decision"}, text={"Comment / justification": "Looks fine."}, select={"Decision": "approve"})
    assert any("confirmation box" in e for e in msgs(r, "error")) and not posted(r, "POST", "/decision")
    r = run(PAGES["review"], clicks={"Record decision"}, checks={CONFIRM: True}, text={"Comment / justification": "Tax difference confirmed with vendor."}, select={"Decision": "approve"})
    call = posted(r, "POST", "/api/invoices/1/decision")[0]
    assert call["body"]["decision"] == "approve" and len(call["body"]["idempotency_key"]) == 32 and call["body"]["comment"].startswith("Tax difference")
    assert any("Decision recorded" in s for s in msgs(r, "success")) and r.stopped == "RerunPage" and "idem_1" not in r.session


def test_idempotency_key_is_stable_across_reruns_until_a_decision_succeeds():
    r1 = run(PAGES["review"])
    r2 = run(PAGES["review"], session={"idem_1": r1.session["idem_1"]})
    assert r1.session["idem_1"] == r2.session["idem_1"]


def test_review_page_warns_about_duplicates_low_confidence_and_serious_findings():
    r = run(PAGES["review"])
    warnings = " ".join(msgs(r, "warning"))
    assert "Duplicate warning" in warnings and "low OCR confidence" in warnings and "written justification" in warnings


def test_payment_needs_an_explicit_confirmation_and_shows_the_erp_reference():
    r = run(PAGES["review"], clicks={"Release payment"})
    assert not posted(r, "POST", "/payment")
    r = run(PAGES["review"], clicks={"Release payment"}, checks={"I confirm the payment of this invoice to the mock ERP.": True})
    assert posted(r, "POST", "/api/invoices/2/payment") and any("PAY-000001" in s for s in msgs(r, "success"))


# ---------------------------------------------------------------- upload
def test_upload_validates_locally_but_leaves_the_real_checks_to_the_server():
    r = run(PAGES["upload"], role="ap_clerk", file=UploadedFile(data=b""), clicks={"Upload and process"})
    assert any("empty" in e for e in msgs(r, "error")) and not posted(r, "POST", "/api/documents")
    r = run(PAGES["upload"], role="ap_clerk", file=UploadedFile(name="x.pdf", data=b"MZ not a pdf"), clicks={"Upload and process"})
    assert any("real PDF" in e for e in msgs(r, "error")) and not posted(r, "POST", "/api/documents")


def test_upload_sends_multipart_and_remembers_the_job():
    r = run(PAGES["upload"], role="ap_clerk", file=UploadedFile(), clicks={"Upload and process"})
    call = posted(r, "POST", "/api/documents")[0]
    assert call["ctype"].startswith("multipart/form-data") and b'filename="inv.pdf"' in call["raw"] and call["raw"].count(b"%PDF") >= 1
    assert r.stopped == "RerunPage" and r.session["last_doc"] == 1 and r.session["last_job"] == "j1" and r.session["uploader_n"] == 1


def test_upload_page_shows_progress_extraction_results_and_failures_honestly():
    ok = run(PAGES["upload"], role="ap_clerk", session={"last_doc": 1, "last_job": "j1"})
    assert not msgs(ok, "error") and posted(ok, "GET", "/api/documents/1") and posted(ok, "GET", "/api/jobs/j1")
    bad = run(PAGES["upload"], role="ap_clerk", session={"last_doc": 1, "last_job": "j2"})
    assert any("Processing failed" in e and "Nothing was approved or paid" in e for e in msgs(bad, "error"))


# ---------------------------------------------------------------- workflow, reports, admin, monitoring
def test_workflow_page_queues_processing_only_for_roles_that_may_process():
    r = run(PAGES["workflow"], role="reviewer", clicks={"Process / re-process this invoice"})
    assert posted(r, "POST", "/api/invoices/1/process")
    r = run(PAGES["workflow"], role="auditor", clicks={"Process / re-process this invoice"})
    assert not posted(r, "POST", "/process")


def test_workflow_page_generates_an_audit_summary_and_labels_its_source():
    r = run(PAGES["workflow"], role="reviewer", clicks={"Generate audit summary"})
    assert posted(r, "POST", "/audit-summary") and any("Template-generated" in m for m in msgs(r, "info"))


def test_reports_export_downloads_come_from_the_api():
    r = run(PAGES["reports"], role="auditor", clicks={"Prepare CSV export"})
    assert posted(r, "GET", "reconciliation.csv") and r.downloads and r.downloads[0][2] > 0


def test_admin_actions_call_the_right_endpoints():
    r = run(PAGES["admin"], role="admin", clicks={"Create user"}, select={"Role": "auditor"},
            text={"Username (a-z, 0-9, . _ -)": "bob", "Password (10+ characters, letters and digits)": "longpassword12"})
    assert posted(r, "POST", "/api/admin/users")[0]["body"] == {"username": "bob", "password": "longpassword12", "role": "auditor"}
    r = run(PAGES["admin"], role="admin", clicks={"Save settings"}, text={"price_tolerance_pct": "2.00"})
    assert posted(r, "PUT", "/api/admin/settings")[0]["body"] == {"values": {"price_tolerance_pct": "2.00"}}
    r = run(PAGES["admin"], role="admin", clicks={"Apply"}, select={"Service": "erp", "Mode": "down"})
    assert posted(r, "POST", "/api/admin/integrations/erp/simulate")[0]["body"]["mode"] == "down"
    r = run(PAGES["admin"], role="admin", clicks={"Save settings"})
    assert not posted(r, "PUT", "/settings") and any("No changes" in m for m in msgs(r, "info"))


def test_monitoring_verifies_the_audit_chain():
    r = run(PAGES["monitoring"], role="auditor", clicks={"Verify audit hash chain"})
    assert any("Chain intact" in m for m in msgs(r, "success"))


# ---------------------------------------------------------------- failure handling
def _server(status, body):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


def test_expired_session_clears_state_and_asks_to_sign_in():
    srv, url = _server(401, {"error": {"code": "INVALID_TOKEN", "message": "expired", "request_id": "r"}})
    ui.state.base_url = lambda: url
    try:
        r = run(PAGES["dashboard"], role="admin")
    finally:
        ui.state.base_url = lambda: URL
        srv.shutdown()
    assert r.stopped == "StopPage" and "token" not in r.session and "user" not in r.session and any("session has ended" in w for w in msgs(r, "warning"))


def test_unreachable_api_shows_a_helpful_message_instead_of_crashing():
    ui.state.base_url = lambda: "http://127.0.0.1:9"
    try:
        r = run(PAGES["dashboard"], role="admin")
    finally:
        ui.state.base_url = lambda: URL
    assert r.stopped == "StopPage" and any("Cannot reach the API" in e and "uvicorn" in e for e in msgs(r, "error"))


def test_server_errors_show_a_reference_and_no_internals():
    srv, url = _server(500, {"error": {"code": "INTERNAL_ERROR", "message": "boom Traceback secret", "request_id": "req-77"}})
    ui.state.base_url = lambda: url
    try:
        r = run(PAGES["dashboard"], role="admin")
    finally:
        ui.state.base_url = lambda: URL
        srv.shutdown()
    text = " ".join(msgs(r, "error"))
    assert "req-77" in text and "Traceback" not in text and "secret" not in text
