import csv
import io
from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from backend.auth.permissions import PERMISSIONS, can, mask_account
from backend.auth.throttle import LoginThrottle, RevokedTokens
from backend.core.metrics import RequestMetrics, aging_buckets, job_stats, llm_stats, percentile
from backend.services.reports import COLUMNS, build_totals, render_csv, render_pdf

ROLES = ("admin", "reviewer", "ap_clerk", "auditor")


def test_permission_matrix_matches_the_role_design():
    assert [can(r, "decide") for r in ROLES] == [True, True, False, False]
    assert [can(r, "pay") for r in ROLES] == [True, True, False, False]
    assert [can(r, "admin") for r in ROLES] == [True, False, False, False]
    assert [can(r, "upload") for r in ROLES] == [True, True, True, False]
    assert all(can(r, "view_records") for r in ROLES)
    assert not can("ghost", "view_records") and not can("admin", "nonexistent_permission")
    assert all(p <= set(ROLES) for p in PERMISSIONS.values())


def test_auditor_is_read_only():
    assert not any(can("auditor", p) for p in ("upload", "process", "decide", "pay", "admin", "view_queue"))


def test_bank_masking():
    assert mask_account("FB12ABCD1234567890") == "**************7890" and mask_account(None) is None and mask_account("12") == "12"


def test_login_throttle_blocks_after_five_failures_and_expires():
    now = [0.0]
    t = LoginThrottle(5, 300, clock=lambda: now[0])
    for _ in range(4):
        t.record_failure("Alice")
    assert not t.blocked("alice")
    t.record_failure("ALICE")
    assert t.blocked("alice") and not t.blocked("bob")
    now[0] = 301
    assert not t.blocked("alice")
    t.record_failure("alice")
    t.reset("alice")
    assert not t.blocked("alice")


def test_revoked_tokens_expire_from_memory():
    now = [100.0]
    r = RevokedTokens(clock=lambda: now[0])
    r.revoke("a", 200)
    assert r.is_revoked("a") and not r.is_revoked("b") and not r.is_revoked(None)
    now[0] = 300
    r.revoke("c", 400)
    assert not r.is_revoked("a")


def test_percentiles_nearest_rank():
    assert percentile([], 50) is None and percentile([5], 95) == 5
    xs = list(range(1, 101))
    assert percentile(xs, 50) == 50 and percentile(xs, 95) == 95 and percentile(xs, 100) == 100


def test_job_stats_failure_rate_and_latency():
    t0 = datetime(2026, 1, 1)
    jobs = [{"status": "SUCCEEDED", "started_at": t0, "finished_at": t0 + timedelta(seconds=s), "attempts": 1} for s in (1, 2, 3, 4)]
    jobs += [{"status": "FAILED", "started_at": t0, "finished_at": t0, "attempts": 3}, {"status": "QUEUED", "attempts": 0}]
    s = job_stats(jobs)
    assert s["succeeded"] == 4 and s["failed"] == 1 and s["failure_rate"] == 0.2 and s["latency_p50_s"] == 2 and s["latency_p95_s"] == 4
    assert s["queued_or_running"] == 1 and s["retried_jobs"] == 1 and job_stats([])["failure_rate"] is None


def test_aging_buckets():
    now = datetime(2026, 10, 26)
    ts = [now, now - timedelta(days=1), now - timedelta(days=3), now - timedelta(days=10), now - timedelta(days=90)]
    assert aging_buckets(ts, now) == {"0-1 days": 2, "2-7 days": 1, "8-30 days": 1, "31+ days": 1}


def test_llm_stats_reports_cost_only_when_provided():
    rows = [{"source": "model", "outcome": "ok", "prompt_tokens": 100, "completion_tokens": 40, "cost_usd": D("0"), "latency_ms": 900},
            {"source": "model", "outcome": "ok", "prompt_tokens": 50, "completion_tokens": 10, "cost_usd": None, "latency_ms": 1100},
            {"source": "template", "outcome": "timeout"}]
    s = llm_stats(rows)
    assert s["prompt_tokens"] == 150 and s["fallback_rate"] == 0.3333 and s["fallback_reasons"] == {"timeout": 1} and s["cost_usd"] == "0"
    assert llm_stats([{"source": "model", "outcome": "ok", "cost_usd": None}])["cost_note"]


def test_request_metrics():
    m = RequestMetrics(size=3)
    for status, ms in [(200, 10), (404, 20), (500, 30), (200, 40)]:
        m.record("/x", status, ms)
    s = m.summary()
    assert s["requests"] == 3 and s["server_error_rate"] == 0.3333 and s["client_errors"] == 1


ROWS = [
    {"invoice_id": 1, "invoice_number": "INV-1", "vendor": "Acme", "invoice_date": "2026-01-01", "currency": "USD", "grand_total": "100.10", "status": "PAID",
     "exception_count": 0, "highest_severity": None, "latest_decision": "approve", "payment_status": "PAID"},
    {"invoice_id": 2, "invoice_number": "=HYPERLINK(\"x\")", "vendor": "Beta", "invoice_date": None, "currency": "USD", "grand_total": "200.20", "status": "AWAITING_REVIEW",
     "exception_count": 2, "highest_severity": "high", "latest_decision": None, "payment_status": "NOT_PAID"},
    {"invoice_id": 3, "invoice_number": "INV-3", "vendor": "Gamma", "invoice_date": "2026-02-02", "currency": "EUR", "grand_total": "50.05", "status": "AWAITING_REVIEW",
     "exception_count": 1, "highest_severity": "low", "latest_decision": None, "payment_status": "NOT_PAID"},
]


def test_report_totals_are_exact_decimals_and_agree_with_rows():
    t = build_totals(ROWS)
    assert t["invoice_count"] == 3 and t["exception_total"] == 3 and t["paid_count"] == 1
    assert t["amount_by_currency"] == {"USD": "300.30", "EUR": "50.05"} and t["by_status"] == {"PAID": 1, "AWAITING_REVIEW": 2}


def test_csv_roundtrip_matches_rows_and_blocks_formula_injection():
    text = render_csv(ROWS)
    lines = text.split("\n\n")[0]
    parsed = list(csv.DictReader(io.StringIO(lines)))
    assert [p["invoice_number"] for p in parsed] == ["INV-1", "'=HYPERLINK(\"x\")", "INV-3"] and list(parsed[0]) == COLUMNS
    assert sum(D(p["grand_total"]) for p in parsed if p["currency"] == "USD") == D("300.30")
    assert "TOTALS,invoices,3,exceptions,3" in text


def test_pdf_report_contains_the_same_totals():
    pdf = render_pdf(ROWS, generated="2026-10-26")
    assert pdf.startswith(b"%PDF")
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        text = "\n".join(p.extract_text() or "" for p in doc.pages)
    assert "Invoices: 3" in text and "USD 300.30" in text and "EUR 50.05" in text and "INV-3" in text


# ---- vendor CSV import (pure) ----------------------------------------------------------------
from backend.services.csv_import import parse_vendor_csv  # noqa: E402


def test_vendor_csv_accepts_good_rows_and_reports_bad_ones_without_aborting():
    text = ("vendor_code,name,tax_id,bank_account,bank_name\n"
            "V9001,Good Co,TX123456789,FB12ABCD1234567890,Demo Bank\n"
            "V9002,Bad Tax,TX12,FB12ABCD1234567890,Demo Bank\n"
            "V9003,,TX123456789,,\n"
            "V9001,Dup Code,TX123456789,,\n"
            "bad code!,X,,,\n"
            "V9004,No Bank,TX987654321,,\n")
    rows, errors = parse_vendor_csv(text)
    assert [r["vendor_code"] for r in rows] == ["V9001", "V9004"] and rows[1]["bank_account"] is None
    assert [e["row"] for e in errors] == [3, 4, 5, 6] and "tax_id" in errors[0]["error"] and "duplicate" in errors[2]["error"]


def test_vendor_csv_requires_header_columns():
    assert parse_vendor_csv("a,b\n1,2\n") == ([], [{"row": 1, "error": "header must include vendor_code, name"}])
