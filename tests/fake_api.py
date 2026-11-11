"""A fake backend that follows the real API contract, for exercising the Streamlit pages."""
import io
import json
import re
import threading
import http.server

from backend.services.doc_text import invoice_lines_text
from scripts.generate_data import build_dataset
from scripts.generate_documents import write_digital_pdf

DS = build_dataset(42)


def pdf_bytes():
    import tempfile, pathlib
    p = pathlib.Path(tempfile.mkdtemp()) / "x.pdf"
    write_digital_pdf(p, invoice_lines_text(DS["invoices"][0]))
    return p.read_bytes()


PDF = pdf_bytes()
INV = {"id": 1, "seq": 1, "invoice_number": "INV-000001", "vendor_id": 1, "vendor": "Acme Supplies Ltd", "invoice_date": "2026-08-01", "due_date": "2026-08-31",
       "po_number": "PO-001001", "grn_number": "GRN-005001", "currency": "USD", "grand_total": "1234.50", "status": "AWAITING_REVIEW", "document_kind": "digital_pdf"}
EXC = [{"id": 11, "invoice_id": 1, "type": "arithmetic", "severity": "high", "rule_id": "ARITH_TAX", "expected": "10.00", "actual": "14.00", "difference": "4.00",
        "message": "Line 1 tax is 14.00 but recalculation gives 10.00", "outcome": "fail", "evidence": {"field": "tax_total", "line_no": 1}, "status": "OPEN", "created_at": "2026-10-01T10:00:00"},
       {"id": 12, "invoice_id": 1, "type": "duplicate", "severity": "medium", "rule_id": "DUP_FUZZY", "expected": "below 0.85", "actual": "0.91", "difference": None,
        "message": "Suspected duplicate", "outcome": "fail", "evidence": {"score": 0.91}, "status": "OPEN", "created_at": "2026-10-01T10:00:00"}]
DETAIL = {"invoice": {**INV, "subtotal": "1100.00", "tax_total": "134.50", "notes": None, "vendor_tax_id": "TX123456789", "bank_account": "**********7890", "data_source": "extracted",
                      "document_id": 1, "version": 3, "created_at": "2026-10-01T09:00:00"},
          "lines": [{"line_no": 1, "description": "Chair", "quantity": "4", "unit_price": "275.00", "discount_pct": "0", "tax_rate": "0.10", "line_total": "1100.00", "tax_amount": "110.00"}],
          "exceptions": EXC,
          "extracted_fields": [{"name": "tax_total", "value": "134.50", "confidence": 1.0, "method": "pdf_text", "page": 1, "snippet": "Tax total: 134.50", "bbox": None},
                               {"name": "line_1", "value": "1 Chair ...", "confidence": 0.55, "method": "ocr_word_conf", "page": 1, "snippet": "1 Chair 4 275.00", "bbox": None},
                               {"name": "currency", "value": None, "confidence": None, "method": "none", "page": None, "snippet": None, "bbox": None}],
          "ai": {"risk_explanation": {"source": "template", "summary": "Automated checks found 2 finding(s).", "items": [{"finding_id": 11, "explanation": "Tax mismatch."}],
                                      "caveats": ["Vendor verification unavailable"], "verification": {"fallback_reason": "timeout", "attempts": [{"n": 1, "outcome": "timeout"}]},
                                      "created_at": "2026-10-01T10:00:00"}},
          "reviews": [], "workflow": {"last_node": "audit", "checkpoints": [{"node": n, "retry_count": 0, "at": "2026-10-01T10:00:00"} for n in ("plan", "vendor", "matching", "explain", "verify", "save", "review_gate", "audit")]},
          "integrations": [{"integration": "vendor_verification", "status": "VERIFIED", "attempts": 1, "at": "2026-10-01T10:00:00", "payment_id": None}],
          "document": {"id": 1, "filename": "inv.pdf", "mime_type": "application/pdf", "kind": "digital_pdf"}}
SUMMARY = {"documents_uploaded": 5, "invoices_total": 520, "invoices_by_status": {"RECEIVED": 500, "AWAITING_REVIEW": 20}, "pending_reviews": 20, "suspected_duplicates": 24,
           "exceptions_by_type": {"arithmetic": 30}, "exceptions_by_severity": {"high": 10, "low": 20}, "open_exceptions": 30,
           "aging_pending_days_since_invoice_date": {"0-1 days": 1, "2-7 days": 2, "8-30 days": 3, "31+ days": 14},
           "jobs": {"total": 4, "succeeded": 3, "failed": 1, "queued_or_running": 0, "failure_rate": 0.25, "retried_jobs": 1, "latency_p50_s": 1.5, "latency_p95_s": 3.0},
           "ai": {"model_calls": 2, "template_fallbacks": 1, "fallback_rate": 0.33, "prompt_tokens": 300, "completion_tokens": 90, "cost_usd": None, "cost_note": "local models report no cost",
                  "model_latency_p50_ms": 900, "model_latency_p95_ms": 1200, "fallback_reasons": {"timeout": 1}}}
RECON_ROW = {"invoice_id": 1, "invoice_number": "INV-000001", "vendor": "Acme", "invoice_date": "2026-08-01", "currency": "USD", "grand_total": "1234.50", "status": "AWAITING_REVIEW",
             "exception_count": 2, "highest_severity": "high", "latest_decision": None, "payment_status": "NOT_PAID"}
HEALTH = {"database": {"healthy": True}, "erp_mock": {"healthy": True, "url": "http://x"}, "vendor_verification_mock": {"healthy": False, "url": "http://y"},
          "llm": {"provider": "ollama", "model": "qwen2.5:1.5b", "available": False}, "ocr": {"tesseract_available": True}}
CALLS = []


def routes():
    page = lambda items, **k: {"items": items, "total": len(items), **k}
    return [
        ("POST", r"/api/auth/login$", lambda b: (200, {"access_token": "tok", "token_type": "bearer", "expires_in": 1800, "username": b["username"], "role": "reviewer"})),
        ("POST", r"/api/auth/logout$", lambda b: (200, {"signed_out": True})),
        ("GET", r"/api/reports/summary", lambda b: (200, SUMMARY)),
        ("GET", r"/api/documents\?|/api/documents$", lambda b: (200, {"items": [{"id": 1, "filename": "inv.pdf", "doc_type": "invoice", "kind": "digital_pdf", "status": "EXTRACTED", "size_bytes": 10,
                                                                               "created_at": "2026-10-01T09:00:00", "job": {"job_id": "j1", "status": "SUCCEEDED", "progress_pct": 100, "attempts": 1, "error": None}, "invoice_id": 1}]})),
        ("GET", r"/api/documents/1/file", lambda b: (200, PDF)),
        ("GET", r"/api/documents/1$", lambda b: (200, {"id": 1, "filename": "inv.pdf", "mime_type": "application/pdf", "doc_type": "invoice", "kind": "digital_pdf", "status": "EXTRACTED", "sha256": "a",
                                                       "fields": DETAIL["extracted_fields"], "job": None, "invoice_id": 1})),
        ("POST", r"/api/documents$", lambda b: (202, {"document_id": 1, "job_id": "j1", "status": "QUEUED"})),
        ("GET", r"/api/jobs/j1", lambda b: (200, {"job_id": "j1", "status": "SUCCEEDED", "job_type": "process_document", "progress_pct": 100, "attempts": 1, "error": None})),
        ("GET", r"/api/jobs/j2", lambda b: (200, {"job_id": "j2", "status": "FAILED", "job_type": "process_invoice", "progress_pct": 40, "attempts": 3, "error": "WorkflowError: boom"})),
        ("GET", r"/api/invoices/1/events", lambda b: (200, {"events": [{"id": 1, "created_at": "2026-10-01T09:00:00", "actor_label": "system:seed", "action": "INVOICE_RECEIVED", "decision": None, "tool_result": {"a": 1}}]})),
        ("POST", r"/api/invoices/1/audit-summary", lambda b: (200, {"source": "template", "label": "Template-generated summary", "summary": "1 audit event(s)", "timeline": ["t | a | b"], "fallback_reason": "unavailable"})),
        ("POST", r"/api/invoices/1/process", lambda b: (202, {"job_id": "j1", "status": "QUEUED"})),
        ("POST", r"/api/invoices/1/decision", lambda b: (200, {"review_id": 5, "invoice_id": 1, "decision": b["decision"], "invoice_status": "APPROVED"})),
        ("POST", r"/api/invoices/2/payment", lambda b: (200, {"status": "PAID", "payment_id": "PAY-000001", "replayed": False, "retry": False, "reason": None})),
        ("GET", r"/api/invoices/1$", lambda b: (200, DETAIL)),
        ("GET", r"/api/invoices\?.*status=APPROVED", lambda b: (200, page([{**INV, "id": 2, "invoice_number": "INV-000002", "status": "APPROVED"}]))),
        ("GET", r"/api/invoices\?.*status=PAYMENT_PENDING", lambda b: (200, page([]))),
        ("GET", r"/api/invoices", lambda b: (200, page([INV]))),
        ("GET", r"/api/review/queue", lambda b: (200, page([{**INV, "open_exceptions": 2, "highest_severity": "high", "explanation_source": "template"}]))),
        ("GET", r"/api/vendors", lambda b: (200, page([{"id": 1, "vendor_code": "V0001", "name": "Acme", "tax_id": "TX123456789", "bank_name": "Demo", "bank_account": "****7890", "verification_status": "VERIFIED", "active": True}]))),
        ("GET", r"/api/purchase-orders/PO-001001", lambda b: (200, {"po_number": "PO-001001", "order_date": "2026-07-01", "currency": "USD", "status": "OPEN", "goods_receipts": ["GRN-005001"], "invoices": ["INV-000001"],
                                                                      "lines": [{"line_no": 1, "description": "Chair", "quantity": "4", "unit_price": "275.00", "tax_rate": "0.10"}]})),
        ("GET", r"/api/purchase-orders", lambda b: (200, page([{"id": 1, "po_number": "PO-001001", "vendor": "Acme", "order_date": "2026-07-01", "currency": "USD", "status": "OPEN", "line_count": 1}]))),
        ("GET", r"/api/goods-receipts", lambda b: (200, page([{"id": 1, "grn_number": "GRN-005001", "po_number": "PO-001001", "receipt_date": "2026-07-10", "lines": [{"po_line_no": 1, "description": "Chair", "quantity_received": "4"}]}]))),
        ("GET", r"/api/reports/reconciliation\.csv", lambda b: (200, b"invoice_id,invoice_number\n1,INV-000001\n")),
        ("GET", r"/api/reports/reconciliation\.pdf", lambda b: (200, PDF)),
        ("GET", r"/api/reports/reconciliation", lambda b: (200, {"rows": [RECON_ROW], "totals": {"invoice_count": 1, "exception_total": 2, "by_status": {"AWAITING_REVIEW": 1}, "amount_by_currency": {"USD": "1234.50"}, "paid_count": 0}})),
        ("GET", r"/api/admin/users", lambda b: (200, {"items": [{"id": 1, "username": "admin", "role": "admin", "is_active": True, "created_at": "2026-10-01T09:00:00"}, {"id": 2, "username": "clerk", "role": "ap_clerk", "is_active": True, "created_at": "2026-10-01T09:00:00"}]})),
        ("POST", r"/api/admin/users$", lambda b: (201, {"id": 9, "username": b["username"], "role": b["role"]})),
        ("PATCH", r"/api/admin/users/\d+", lambda b: (200, {"id": 2, "username": "clerk", "role": b.get("role", "ap_clerk"), "is_active": True})),
        ("GET", r"/api/admin/settings", lambda b: (200, {"items": [{"key": "price_tolerance_pct", "value": "1.00", "description": "Allowed price diff", "updated_at": "2026-10-01T09:00:00"}]})),
        ("PUT", r"/api/admin/settings", lambda b: (200, {"updated": {k: {"old": "1.00", "new": v} for k, v in b["values"].items()}})),
        ("GET", r"/api/admin/integrations", lambda b: (200, HEALTH)),
        ("POST", r"/api/admin/integrations/(erp|vendor)/simulate", lambda b: (200, {"integration": "erp", "mode": b["mode"]})),
        ("GET", r"/api/monitoring/metrics", lambda b: (200, {"jobs": SUMMARY["jobs"], "ai": SUMMARY["ai"], "api": {"requests": 40, "server_error_rate": 0.0, "client_errors": 3, "p50_ms": 12.0, "p95_ms": 80.0},
                                                             "failures": [{"job_id": "j2", "type": "process_invoice", "status": "FAILED", "error_class": "WorkflowError", "message": "boom", "attempts": 3, "invoice_id": 1}], "integrations": HEALTH})),
        ("GET", r"/api/audit/verify", lambda b: (200, {"chain_ok": True, "first_bad_event_id": None, "events": 9, "note": "tamper-evident"})),
    ]


def start():
    table = [(m, re.compile(p), f) for m, p, f in routes()]

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _handle(self, method):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            ctype = self.headers.get("Content-Type", "")
            body = json.loads(raw) if raw and ctype.startswith("application/json") else {}
            CALLS.append({"method": method, "path": self.path, "body": body, "raw": raw, "auth": self.headers.get("Authorization"), "ctype": ctype})
            for m, rx, fn in table:
                if m == method and rx.search(self.path):
                    status, payload = fn(body)
                    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                    self.send_response(status)
                    self.send_header("Content-Type", "application/octet-stream" if isinstance(payload, bytes) else "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    if isinstance(payload, bytes):
                        self.send_header("Content-Disposition", 'attachment; filename="export.bin"')
                    self.end_headers()
                    self.wfile.write(data)
                    return
            data = json.dumps({"error": {"code": "NOT_FOUND", "message": f"fake api has no route {method} {self.path}"}}).encode()
            self.send_response(404)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = lambda self: self._handle("GET")
        do_POST = lambda self: self._handle("POST")
        do_PUT = lambda self: self._handle("PUT")
        do_PATCH = lambda self: self._handle("PATCH")

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"
