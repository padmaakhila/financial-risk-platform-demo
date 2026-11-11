"""Evaluation harness: accuracy against ground truth, latency (p50/p95), error rate, AI usage, optional pytest counts.

  python -m scripts.run_evaluation                      # auto: 'full' when SQLAlchemy is installed, else 'pure'
  python -m scripts.run_evaluation --mode pure          # no database: Matching Service + explanation only
  python -m scripts.run_evaluation --mode full --with-tests
  python -m scripts.run_evaluation --provider ollama --limit 25    # real local model (slow on a laptop)

Writes reports/evaluation_report.md and reports/evaluation_results.json. Nothing here is invented: every number
comes from the run that produced the file, and the report states which mode produced it."""
from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.agents.llm import FakeProvider, NullProvider
from backend.agents.risk_explainer import explain_findings
from backend.core.config import BASE_DIR
from backend.core.metrics import percentile
from backend.services.matching import evaluate_invoice
from backend.services.rules import Tolerances
from scripts.generate_data import SCENARIOS, build_dataset

BEHAVIOURAL = {"S18_UNSUPPORTED_FILE": "tests/test_upload_validation.py", "S21_VENDOR_OUTAGE": "tests/test_workflow.py, tests/test_workflow_db.py",
               "S22_ERP_OUTAGE": "tests/test_review_payments.py", "S23_UNAUTHORIZED_API": "tests/test_api.py", "S24_PAYMENT_NO_APPROVAL": "tests/test_review_payments.py, tests/test_api.py",
               "S16_UNREADABLE_SCAN": "tests/test_extraction.py (real Tesseract)", "S17_LOW_CONF_OCR": "tests/test_extraction.py"}


def expected_rules(truth: dict) -> set[str]:
    e = truth["expected"]
    return {r for r in e["rules"] + e["warnings"] if not r.startswith("DOC_")}


def make_provider(kind: str):
    if kind == "ollama":
        from backend.agents.llm import OllamaProvider
        from backend.core.config import get_settings
        s = get_settings()
        return OllamaProvider(s.ollama_url, s.ollama_model)
    return NullProvider()


# ------------------------------------------------------------------ pure mode (no database)
def run_pure(ds: dict, provider, limit: int | None, timeout: float) -> dict:
    vendors = {v["vendor_code"]: v for v in ds["vendors"]}
    pos = {p["po_number"]: p for p in ds["purchase_orders"]}
    grns = {g["grn_number"]: g for g in ds["goods_receipts"]}
    truth = {t["invoice_seq"]: t for t in ds["ground_truth"] if t["invoice_seq"]}
    by_vendor, by_total = {}, {}
    for i in ds["invoices"]:
        by_vendor.setdefault(i["vendor_code"], []).append(i)
        by_total.setdefault(i["grand_total"], []).append(i)
    rows = []
    for inv in ds["invoices"][:limit]:
        t = truth[inv["seq"]]
        prov = FakeProvider([("sleep", timeout * 4, "{}")]) if (t["scenario_code"] == "S20_LLM_TIMEOUT" and isinstance(provider, NullProvider)) else provider
        err, start = None, time.perf_counter()
        try:
            priors = {id(o): o for o in by_vendor[inv["vendor_code"]] + by_total.get(inv["grand_total"], []) if o["seq"] < inv["seq"]}.values()
            res = evaluate_invoice(inv, vendor=vendors[inv["vendor_code"]], po=pos.get(inv["po_number"]), grn=grns.get(inv["grn_number"]),
                                   prior_invoices=list(priors), tolerances=Tolerances())
            findings = [f.to_dict(n) for n, f in enumerate(res.findings, 1)]
            summary = {k: (str(inv[k]) if inv[k] is not None else None) for k in ("invoice_number", "vendor_name_raw", "currency", "subtotal", "tax_total", "grand_total")}
            expl = explain_findings(prov, summary, findings, [], max_retries=2, timeout=timeout)
            got, source, reason, usage = res.rule_ids, expl.source, expl.fallback_reason, expl.usage
        except Exception as exc:  # recorded as an error, never hidden
            err, got, source, reason, usage = type(exc).__name__, set(), None, None, []
        rows.append({"seq": inv["seq"], "scenario": t["scenario_code"], "expected": sorted(expected_rules(t)), "got": sorted(got), "ok": err is None and got == expected_rules(t),
                     "latency_s": time.perf_counter() - start, "error": err, "explanation_source": source, "fallback_reason": reason, "usage": usage})
    return {"mode": "pure", "rows": rows, "notes": ["Pure mode: no database, no OCR, no mock services. Latency covers matching + explanation only.",
                                                     "Explanations are template-generated unless --provider ollama is used."]}


# ------------------------------------------------------------------ full mode (database + workflow + mocks)
def run_full(ds: dict, provider, limit: int | None, timeout: float) -> dict:
    from sqlalchemy import func, select
    from sqlalchemy.orm import sessionmaker
    from backend.agents.tools import ToolRegistry
    from backend.agents.workflow import WorkflowConfig, WorkflowContext, initial_state, run_workflow
    from backend.agents.workflow_db import make_db_tools
    from backend.database.session import make_engine, session_scope
    from backend.integrations.clients import ErpClient, VendorVerificationClient
    from backend.integrations.erp_mock_core import ErpMock
    from backend.integrations.mock_server import start_in_thread
    from backend.integrations.vendor_mock_core import VendorMock
    from backend.models import AiOutput, Base, ExceptionRecord, Invoice, LlmUsage, User
    from backend.services.audit import verify_audit_chain
    from backend.services.payments import ApprovalRequired, pay_invoice
    from backend.services.review import record_decision
    from scripts.seed_database import seed

    tmp = Path(tempfile.mkdtemp())
    engine = make_engine(f"sqlite:///{(tmp / 'eval.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_scope(factory) as s:
        seed(s, ds)
    v_srv, v_url = start_in_thread(VendorMock.from_dataset(ds))
    erp_core = ErpMock(timeout_delay=1.0)
    e_srv, e_url = start_in_thread(erp_core)
    vendor_client, erp_client = VendorVerificationClient(v_url, timeout=2), ErpClient(e_url, timeout=1, sleep=lambda s: None)
    truth = {t["invoice_seq"]: t for t in ds["ground_truth"] if t["invoice_seq"]}
    rows = []
    try:
        with session_scope(factory) as s:
            ids = {i.seq: i.id for i in s.scalars(select(Invoice).order_by(Invoice.seq).limit(limit))}
        for seq, inv_id in ids.items():
            t = truth[seq]
            prov = FakeProvider([("sleep", timeout * 4, "{}")]) if (t["scenario_code"] == "S20_LLM_TIMEOUT" and isinstance(provider, NullProvider)) else provider
            ctx = WorkflowContext(ToolRegistry(make_db_tools(factory, vendor_client)), prov, WorkflowConfig(llm_timeout=timeout))
            start, err = time.perf_counter(), None
            try:
                run_workflow(ctx, initial_state(inv_id))
            except Exception as exc:
                err = type(exc).__name__
            latency = time.perf_counter() - start
            with session_scope(factory) as s:
                got = {e.rule_id for e in s.scalars(select(ExceptionRecord).where(ExceptionRecord.invoice_id == inv_id))}
                out = s.scalar(select(AiOutput).where(AiOutput.invoice_id == inv_id))
            exp = expected_rules(t) | ({"DOC_LOW_CONF"} if False else set())
            rows.append({"seq": seq, "scenario": t["scenario_code"], "expected": sorted(exp), "got": sorted(got), "ok": err is None and got == exp, "latency_s": latency, "error": err,
                         "explanation_source": out.source if out else None, "fallback_reason": (out.verification or {}).get("fallback_reason") if out else None, "usage": []})
        checks = []
        with session_scope(factory) as s:
            users = {u.username: (u.id, u.role) for u in s.scalars(select(User))}
            pay_id = s.scalar(select(Invoice.id).where(Invoice.status == "AWAITING_REVIEW").limit(1))
        uid, role = users["reviewer"]
        try:
            pay_invoice(factory, erp_client, invoice_id=pay_id, actor_id=uid, actor_role=role)
            checks.append(("Payment without approval is blocked", False))
        except ApprovalRequired:
            checks.append(("Payment without approval is blocked", True))
        with session_scope(factory) as s:
            record_decision(s, invoice_id=pay_id, reviewer_id=uid, reviewer_role=role, decision="approve", comment="evaluation run: approved after review of findings", idempotency_key="eval-1")
        first = pay_invoice(factory, erp_client, invoice_id=pay_id, actor_id=uid, actor_role=role)
        again = pay_invoice(factory, erp_client, invoice_id=pay_id, actor_id=uid, actor_role=role)
        checks.append(("Approved invoice is paid exactly once, retries are idempotent", first["status"] == "PAID" and again["status"] == "PAID" and len(erp_core.payments) == 1))
        with session_scope(factory) as s:
            second = s.scalar(select(Invoice.id).where(Invoice.status == "AWAITING_REVIEW").limit(1))
            record_decision(s, invoice_id=second, reviewer_id=uid, reviewer_role=role, decision="approve", comment="evaluation run: approved after review", idempotency_key="eval-2")
        erp_core.handle("POST", "/admin/simulate", {}, {"mode": "down"})
        down = pay_invoice(factory, erp_client, invoice_id=second, actor_id=uid, actor_role=role)
        erp_core.handle("POST", "/admin/simulate", {}, {"mode": "normal"})
        with session_scope(factory) as s:
            status = s.get(Invoice, second).status
        checks.append(("ERP outage leaves the invoice PAYMENT_PENDING, never PAID", down["status"] == "PAYMENT_PENDING" and status == "PAYMENT_PENDING"))
        with session_scope(factory) as s:
            chain_ok = verify_audit_chain(s)[0]
            usage = [{"prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens, "cost_usd": str(u.cost_usd) if u.cost_usd is not None else None}
                     for u in s.scalars(select(LlmUsage).where(LlmUsage.source == "model"))]
        checks.append(("Audit hash chain is intact after the run", chain_ok))
    finally:
        v_srv.shutdown()
        e_srv.shutdown()
    if usage and rows:
        rows[0]["usage"] = usage
    return {"mode": "full", "rows": rows, "checks": checks, "notes": ["Full mode: SQLite database, workflow with allowlisted tools, mock vendor and ERP services over HTTP."]}


# ------------------------------------------------------------------ aggregation + report
def summarize(result: dict) -> dict:
    rows = result["rows"]
    lat = [r["latency_s"] for r in rows]
    tp = sum(len(set(r["got"]) & set(r["expected"])) for r in rows)
    fp = sum(len(set(r["got"]) - set(r["expected"])) for r in rows)
    fn = sum(len(set(r["expected"]) - set(r["got"])) for r in rows)
    per = {}
    for r in rows:
        p = per.setdefault(r["scenario"], {"n": 0, "exact": 0, "errors": 0})
        p["n"] += 1
        p["exact"] += 1 if r["ok"] else 0
        p["errors"] += 1 if r["error"] else 0
    usage = [u for r in rows for u in r["usage"]]
    costs = [u["cost_usd"] for u in usage if u.get("cost_usd") is not None]
    srcs = [r["explanation_source"] for r in rows if r["explanation_source"]]
    return {"invoices": len(rows), "exact_match": sum(1 for r in rows if r["ok"]), "errors": sum(1 for r in rows if r["error"]),
            "error_rate": round(sum(1 for r in rows if r["error"]) / len(rows), 4) if rows else None,
            "precision": round(tp / (tp + fp), 4) if tp + fp else None, "recall": round(tp / (tp + fn), 4) if tp + fn else None, "tp": tp, "fp": fp, "fn": fn,
            "latency_p50_ms": round(percentile(lat, 50) * 1000, 1) if lat else None, "latency_p95_ms": round(percentile(lat, 95) * 1000, 1) if lat else None,
            "latency_max_ms": round(max(lat) * 1000, 1) if lat else None, "per_scenario": per, "model_explanations": srcs.count("model"), "template_explanations": srcs.count("template"),
            "fallback_reasons": {k: sum(1 for r in rows if r["fallback_reason"] == k) for k in {r["fallback_reason"] for r in rows if r["fallback_reason"]}},
            "prompt_tokens": sum(u.get("prompt_tokens") or 0 for u in usage), "completion_tokens": sum(u.get("completion_tokens") or 0 for u in usage), "cost_reported": bool(costs),
            "avg_tokens_per_task": round(sum((u.get("prompt_tokens") or 0) + (u.get("completion_tokens") or 0) for u in usage) / len(rows), 1) if usage and rows else None}


def run_tests() -> dict:
    try:
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider"], cwd=BASE_DIR, capture_output=True, text=True, timeout=1800)
    except Exception as exc:
        return {"ran": False, "note": f"pytest could not be started: {type(exc).__name__}"}
    tail = (p.stdout.strip().splitlines() or [""])[-1]
    m = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|skipped|error|errors|deselected)", tail)}
    return {"ran": True, "summary": tail, "counts": m, "exit_code": p.returncode}


def write_report(result: dict, s: dict, args, tests: dict | None, out: Path) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L = [f"# Evaluation report", "", f"Generated {now} by `scripts/run_evaluation.py` (mode **{result['mode']}**, provider **{args.provider}**, seed {args.seed}, "
         f"Python {platform.python_version()} on {platform.system()}). All data is synthetic.", ""]
    L += [f"> {n}" for n in result["notes"]] + [""]
    L += ["## Headline results", "", "| Measure | Result |", "|---|---|",
          f"| Invoices evaluated | {s['invoices']} |", f"| Exact match with ground truth | {s['exact_match']} / {s['invoices']} |",
          f"| Rule-level precision / recall | {s['precision']} / {s['recall']} (TP {s['tp']}, FP {s['fp']}, FN {s['fn']}) |",
          f"| Errors (exceptions raised) | {s['errors']} (rate {s['error_rate']}) |",
          f"| Workflow latency p50 / p95 / max | {s['latency_p50_ms']} ms / {s['latency_p95_ms']} ms / {s['latency_max_ms']} ms |",
          f"| Explanations: model / template | {s['model_explanations']} / {s['template_explanations']} |",
          f"| Template fallback reasons | {s['fallback_reasons'] or 'none'} |",
          f"| Tokens (prompt + completion) | {s['prompt_tokens']} + {s['completion_tokens']} |",
          f"| Average tokens per task | {s['avg_tokens_per_task'] if s['avg_tokens_per_task'] is not None else 'n/a (no model calls)'} |",
          f"| Cost | {'reported by provider' if s['cost_reported'] else 'not reported (local model or template only), so no cost per task is claimed'} |", ""]
    L += ["## Results by scenario", "", "| Scenario | Invoices | Exact match | Errors | Also covered by |", "|---|---|---|---|---|"]
    for code, desc, _ in SCENARIOS:
        p = s["per_scenario"].get(code)
        L.append(f"| {code} | {p['n'] if p else 0} | {p['exact'] if p else 'n/a'} | {p['errors'] if p else 'n/a'} | {BEHAVIOURAL.get(code, 'tests/test_matching.py')} |")
    if result.get("checks"):
        L += ["", "## Acceptance spot-checks (full mode)", "", "| Check | Result |", "|---|---|"] + [f"| {n} | {'PASS' if ok else 'FAIL'} |" for n, ok in result["checks"]]
    L += ["", "## Automated test suite", ""]
    if tests and tests.get("ran"):
        L += [f"`{tests['summary']}` (exit code {tests['exit_code']})."]
    else:
        L += [(tests or {}).get("note", "Not run in this report. Run `python -m scripts.run_evaluation --with-tests` or `python -m pytest -q` and paste the summary line here.")]
    L += ["", "## Limitations (read these)", "",
          "- The ground truth is generated by the same project, with errors planted on purpose. Perfect scores here show the rules do what the design says; they do **not** predict accuracy on real invoices.",
          "- Scenarios that need a real OCR engine, the network, or a browser (S16, S17, S18, S21-S24) are verified by the pytest suite, not by this table.",
          "- Latency depends on the machine; with a local model on an 8 GB laptop the explanation step dominates and can exceed 30 s, which triggers the template fallback by design.",
          "- No cloud model was used, so no per-task cost is claimed. If you enable an external API, record its reported usage here yourself.",
          "- Template explanations are always available; model explanations are accepted only after deterministic verification.", ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["auto", "pure", "full"], default="auto")
    ap.add_argument("--provider", choices=["none", "ollama"], default="none")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--limit", type=int, default=None, help="evaluate only the first N invoices (default: all; 25 with ollama)")
    ap.add_argument("--timeout", type=float, default=0.3, help="LLM deadline in seconds (use 30 with ollama)")
    ap.add_argument("--with-tests", action="store_true")
    ap.add_argument("--out", default=str(BASE_DIR / "reports" / "evaluation_report.md"))
    args = ap.parse_args()
    mode = args.mode
    if mode == "auto":
        try:
            import sqlalchemy  # noqa: F401
            mode = "full"
        except ImportError:
            mode = "pure"
    limit = args.limit or (25 if args.provider == "ollama" else None)
    timeout = 30.0 if args.provider == "ollama" and args.timeout == 0.3 else args.timeout
    ds, provider = build_dataset(args.seed), make_provider(args.provider)
    result = (run_full if mode == "full" else run_pure)(ds, provider, limit, timeout)
    summary = summarize(result)
    tests = run_tests() if args.with_tests else None
    out = Path(args.out)
    write_report(result, summary, args, tests, out)
    out.with_suffix(".json").write_text(json.dumps({"mode": result["mode"], "summary": summary, "checks": result.get("checks"), "tests": tests}, indent=1, default=str), encoding="utf-8")
    print(f"mode={result['mode']} invoices={summary['invoices']} exact={summary['exact_match']} errors={summary['errors']} "
          f"p50={summary['latency_p50_ms']}ms p95={summary['latency_p95_ms']}ms -> {out}")


if __name__ == "__main__":
    main()
