"""Pure metric helpers (percentiles, job statistics, aging buckets, request metrics). No database access."""
from __future__ import annotations

import math
import threading
from collections import deque
from datetime import datetime
from decimal import Decimal


def percentile(values, p: float):
    """Nearest-rank percentile (p in 0..100). Returns None for an empty list."""
    xs = sorted(values)
    if not xs:
        return None
    k = max(1, math.ceil(p / 100 * len(xs)))
    return xs[k - 1]


def job_stats(jobs: list[dict]) -> dict:
    """jobs: {status, started_at, finished_at, attempts}. Latency counts only SUCCEEDED jobs."""
    done = [j for j in jobs if j["status"] in ("SUCCEEDED", "FAILED")]
    lat = [(j["finished_at"] - j["started_at"]).total_seconds() for j in jobs
           if j["status"] == "SUCCEEDED" and j.get("started_at") and j.get("finished_at")]
    failed = sum(1 for j in done if j["status"] == "FAILED")
    return {"total": len(jobs), "succeeded": sum(1 for j in jobs if j["status"] == "SUCCEEDED"), "failed": failed,
            "queued_or_running": sum(1 for j in jobs if j["status"] in ("QUEUED", "RUNNING", "RETRYING")),
            "failure_rate": round(failed / len(done), 4) if done else None, "retried_jobs": sum(1 for j in jobs if j.get("attempts", 0) > 1),
            "latency_p50_s": percentile(lat, 50), "latency_p95_s": percentile(lat, 95)}


AGING_BUCKETS = (("0-1 days", 0, 1), ("2-7 days", 2, 7), ("8-30 days", 8, 30), ("31+ days", 31, 10 ** 6))


def aging_buckets(created_times: list[datetime], now: datetime) -> dict:
    out = {name: 0 for name, _, _ in AGING_BUCKETS}
    for t in created_times:
        days = max(0, (now - t).days)
        for name, lo, hi in AGING_BUCKETS:
            if lo <= days <= hi:
                out[name] += 1
                break
    return out


def llm_stats(rows: list[dict]) -> dict:
    """rows: {source, outcome, prompt_tokens, completion_tokens, cost_usd, latency_ms}"""
    model = [r for r in rows if r["source"] == "model"]
    template = [r for r in rows if r["source"] == "template"]
    cost = [r["cost_usd"] for r in model if r.get("cost_usd") is not None]
    lat = [r["latency_ms"] for r in model if r.get("latency_ms") is not None]
    return {"model_calls": len(model), "template_fallbacks": len(template),
            "fallback_rate": round(len(template) / (len(model) + len(template)), 4) if (model or template) else None,
            "prompt_tokens": sum(r.get("prompt_tokens") or 0 for r in model), "completion_tokens": sum(r.get("completion_tokens") or 0 for r in model),
            "cost_usd": str(sum(cost, Decimal("0"))) if cost else None, "cost_note": "local models report no cost" if model and not cost else None,
            "model_latency_p50_ms": percentile(lat, 50), "model_latency_p95_ms": percentile(lat, 95),
            "fallback_reasons": _count([r["outcome"] for r in template])}


def _count(items) -> dict:
    out: dict = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return out


class RequestMetrics:
    """Rolling window of API request outcomes (process-local)."""

    def __init__(self, size: int = 2000):
        self._items, self._lock = deque(maxlen=size), threading.Lock()

    def record(self, path: str, status: int, ms: float) -> None:
        with self._lock:
            self._items.append((path, status, ms))

    def summary(self) -> dict:
        with self._lock:
            items = list(self._items)
        ms = [i[2] for i in items]
        errors = sum(1 for i in items if i[1] >= 500)
        return {"requests": len(items), "server_error_rate": round(errors / len(items), 4) if items else None,
                "client_errors": sum(1 for i in items if 400 <= i[1] < 500), "p50_ms": percentile(ms, 50), "p95_ms": percentile(ms, 95)}
