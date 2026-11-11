"""Tool allowlist. Agents and the workflow can call ONLY these names; everything else raises.
There is deliberately no tool for payments, approvals, arbitrary SQL, shell or code execution:
payments exist only in backend/services/payments.py behind a recorded human approval."""
from __future__ import annotations
import time
from typing import Callable

ALLOWED_TOOLS = frozenset({
    "get_invoice_summary", "verify_vendor", "run_matching", "list_findings", "record_exception",
    "save_explanation", "set_status", "append_audit", "save_checkpoint", "load_events",
})
NEVER_ALLOWED = frozenset({"post_payment", "approve_invoice", "execute_python", "run_sql", "shell", "update_amount", "delete_record"})


class ToolNotAllowed(Exception):
    pass


class ToolRegistry:
    def __init__(self, impls: dict, trace_callback: Callable[[dict], None] | None = None):
        bad = set(impls) - ALLOWED_TOOLS
        if bad:
            raise ToolNotAllowed(f"refusing to register non-allowlisted tools: {sorted(bad)}")
        self._impls = impls
        self.log: list[dict] = []
        self.trace_callback = trace_callback

    def call(self, name: str, **kwargs):
        if name not in ALLOWED_TOOLS or name not in self._impls:
            entry = {"tool": name, "ok": False, "error": "ToolNotAllowed", "args": sorted(kwargs), "invoice_id": kwargs.get("invoice_id")}
            self.log.append(entry)
            if self.trace_callback: self.trace_callback(entry)
            raise ToolNotAllowed(f"tool '{name}' is not on the allowlist")
        entry = {"tool": name, "args": sorted(kwargs), "invoice_id": kwargs.get("invoice_id")}
        started = time.monotonic()
        try:
            result = self._impls[name](**kwargs)
        except Exception as exc:
            event = {**entry, "ok": False, "error": type(exc).__name__, "duration_ms": int((time.monotonic()-started)*1000)}
            self.log.append(event)
            if self.trace_callback: self.trace_callback(event)
            raise
        event = {**entry, "ok": True, "duration_ms": int((time.monotonic()-started)*1000)}
        self.log.append(event)
        if self.trace_callback: self.trace_callback(event)
        return result
