"""Generate docs/postman_collection.json (Postman v2.1) from the endpoint list below.
Import the file in Postman, run "Auth / Login (reviewer)" first: its test script stores the token in {{token}}."""
import json
from pathlib import Path

IDEM = "{{$guid}}"
J = [{"key": "Content-Type", "value": "application/json"}]


def req(name, method, path, body=None, auth=True, desc="", query=None, form=None, tests=None):
    r = {"method": method, "header": list(J) if body is not None else [], "url": {"raw": "{{baseUrl}}" + path, "host": ["{{baseUrl}}"], "path": [p for p in path.strip("/").split("/")]},
         "description": desc}
    if query:
        r["url"]["query"] = [{"key": k, "value": v} for k, v in query.items()]
        r["url"]["raw"] += "?" + "&".join(f"{k}={v}" for k, v in query.items())
    if body is not None:
        r["body"] = {"mode": "raw", "raw": json.dumps(body, indent=2), "options": {"raw": {"language": "json"}}}
    if form:
        r["body"] = {"mode": "formdata", "formdata": form}
    r["auth"] = {"type": "bearer", "bearer": [{"key": "token", "value": "{{token}}", "type": "string"}]} if auth else {"type": "noauth"}
    item = {"name": name, "request": r}
    if tests:
        item["event"] = [{"listen": "test", "script": {"type": "text/javascript", "exec": tests}}]
    return item


def login(user, pw):
    return req(f"Login ({user})", "POST", "/api/auth/login", {"username": user, "password": pw}, auth=False, desc="Demo credentials are printed by scripts.seed_database (development only).",
               tests=['pm.test("200 OK", () => pm.response.to.have.status(200));', 'pm.collectionVariables.set("token", pm.response.json().access_token);'])


FOLDERS = {
    "Auth": [login("reviewer", "Review#Demo2026"), login("admin", "Admin#Demo2026"), login("clerk", "Clerk#Demo2026"), login("auditor", "Audit#Demo2026"),
             req("Wrong password (expect 401)", "POST", "/api/auth/login", {"username": "admin", "password": "wrong"}, auth=False),
             req("Who am I", "GET", "/api/auth/me"), req("Logout", "POST", "/api/auth/logout")],
    "Unauthorized checks (expect 401/403)": [
        req("No token: list invoices (401)", "GET", "/api/invoices", auth=False), req("No token: decision (401)", "POST", "/api/invoices/1/decision", {"decision": "approve", "idempotency_key": "x"}, auth=False),
        req("Clerk token: admin users (403)", "GET", "/api/admin/users", desc="Log in as clerk first.")],
    "Documents": [
        req("Upload a PDF/PNG/JPG (or vendor CSV)", "POST", "/api/documents", form=[{"key": "file", "type": "file", "src": []}], desc="Choose a file in the body tab. Returns 202 with a job_id."),
        req("List documents", "GET", "/api/documents", query={"limit": "20"}), req("Get document + extracted fields", "GET", "/api/documents/1"), req("Get original file (evidence)", "GET", "/api/documents/1/file"),
        req("Job status", "GET", "/api/jobs/{{jobId}}", desc="Set the jobId collection variable from the upload response.")],
    "Invoices and records": [
        req("List invoices", "GET", "/api/invoices", query={"status": "AWAITING_REVIEW", "limit": "20"}), req("Invoice detail (findings, evidence, AI explanation)", "GET", "/api/invoices/1"),
        req("Process invoice (queue workflow)", "POST", "/api/invoices/1/process"), req("Audit events for invoice", "GET", "/api/invoices/1/events"),
        req("Audit summary (AI or template)", "POST", "/api/invoices/1/audit-summary"), req("Vendors", "GET", "/api/vendors", query={"q": "Acme"}),
        req("Purchase orders", "GET", "/api/purchase-orders"), req("Purchase order detail", "GET", "/api/purchase-orders/PO-001001"), req("Goods receipts", "GET", "/api/goods-receipts")],
    "Review and payment": [
        req("Review queue", "GET", "/api/review/queue"),
        req("Approve", "POST", "/api/invoices/1/decision", {"decision": "approve", "comment": "Checked against PO and GRN.", "idempotency_key": IDEM}),
        req("Reject", "POST", "/api/invoices/1/decision", {"decision": "reject", "comment": "Duplicate of an earlier invoice.", "idempotency_key": IDEM}),
        req("Request documents", "POST", "/api/invoices/1/decision", {"decision": "request_documents", "comment": "Please send the goods-received note.", "idempotency_key": IDEM}),
        req("Release payment (409 APPROVAL_REQUIRED without approval)", "POST", "/api/invoices/1/payment")],
    "Reports": [req("Dashboard summary", "GET", "/api/reports/summary"), req("Reconciliation (JSON)", "GET", "/api/reports/reconciliation"),
                req("Reconciliation CSV", "GET", "/api/reports/reconciliation.csv"), req("Reconciliation PDF", "GET", "/api/reports/reconciliation.pdf")],
    "Admin": [req("List users", "GET", "/api/admin/users"), req("Create user", "POST", "/api/admin/users", {"username": "newuser", "password": "StrongPass123", "role": "ap_clerk"}),
              req("Update user", "PATCH", "/api/admin/users/2", {"role": "auditor"}), req("Get settings", "GET", "/api/admin/settings"),
              req("Update settings", "PUT", "/api/admin/settings", {"values": {"price_tolerance_pct": "2.00"}}), req("Integration health", "GET", "/api/admin/integrations"),
              req("Simulate ERP outage", "POST", "/api/admin/integrations/erp/simulate", {"mode": "down", "fail_n": 2}),
              req("Restore ERP", "POST", "/api/admin/integrations/erp/simulate", {"mode": "normal", "fail_n": 0})],
    "Monitoring and health": [req("Metrics", "GET", "/api/monitoring/metrics"), req("Verify audit chain", "GET", "/api/audit/verify"), req("Audit events", "GET", "/api/audit/events", query={"limit": "50"}),
                              req("Health (no auth)", "GET", "/api/health", auth=False)],
    "Mock ERP (port 8101)": [
        {"name": "Post payment", "request": {"method": "POST", "header": J + [{"key": "Idempotency-Key", "value": "demo-key-1"}], "url": {"raw": "{{erpUrl}}/payments"},
                                              "body": {"mode": "raw", "raw": json.dumps({"invoice_number": "INV-000001", "vendor_code": "V0001", "amount": "123.45", "currency": "USD", "approval_id": "7"}, indent=2)}}},
        {"name": "Simulate outage", "request": {"method": "POST", "header": J, "url": {"raw": "{{erpUrl}}/admin/simulate"}, "body": {"mode": "raw", "raw": '{"mode": "down"}'}}}],
    "Mock vendor verification (port 8102)": [
        {"name": "Verify vendor", "request": {"method": "POST", "header": J, "url": {"raw": "{{vendorUrl}}/verify"}, "body": {"mode": "raw", "raw": '{"tax_id": "TX123456789", "bank_account": "FB12ABCD1234567890"}'}}}],
}
collection = {"info": {"name": "Financial Document & Risk Analysis Platform", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
                       "description": "Synthetic data only. Run Auth > Login first."},
              "variable": [{"key": "baseUrl", "value": "http://localhost:8000"}, {"key": "token", "value": ""}, {"key": "jobId", "value": ""},
                           {"key": "erpUrl", "value": "http://localhost:8101"}, {"key": "vendorUrl", "value": "http://localhost:8102"}],
              "item": [{"name": n, "item": items} for n, items in FOLDERS.items()]}

if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "docs" / "postman_collection.json"
    out.write_text(json.dumps(collection, indent=2), encoding="utf-8")
    print(f"wrote {out} with {sum(len(v) for v in FOLDERS.values())} requests")
