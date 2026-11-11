"""Mock vendor-verification API (core logic, framework-free). Fictional vendors only.

POST /verify  body: {tax_id, bank_account?, vendor_code?}
  200 -> {request_id, status: VERIFIED|REJECTED|NOT_FOUND|INVALID, tax_id_status: VERIFIED|REJECTED|NOT_FOUND|INVALID_FORMAT,
          bank_status: MATCH|MISMATCH|NOT_PROVIDED, checked_at_utc}
  422 missing tax_id | 503 simulated outage | (timeout mode sleeps)
GET /health, POST /admin/simulate {"mode": normal|down|timeout|flaky|reject_all, "fail_n": 2}, POST /admin/reset"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from backend.core.constants import TAX_ID_REGEX


class VendorMock:
    def __init__(self, vendors: list[dict] | None = None, timeout_delay: float = 5.0):
        self.records = {v["tax_id"]: v for v in (vendors or [])}
        self.timeout_delay = timeout_delay
        self.reset()

    @classmethod
    def from_dataset(cls, dataset: dict, **kw) -> "VendorMock":
        return cls(dataset["vendors"], **kw)

    def reset(self):
        self.mode, self.fail_n, self.calls, self.seq = "normal", 0, 0, 0

    def handle(self, method: str, path: str, headers: dict, body: dict | None) -> tuple[int, dict]:
        body = body or {}
        if path == "/admin/simulate" and method == "POST":
            mode = body.get("mode", "normal")
            if mode not in ("normal", "down", "timeout", "flaky", "reject_all"):
                return 422, {"error": "unknown mode"}
            self.mode, self.fail_n, self.calls = mode, int(body.get("fail_n", 2)), 0
            return 200, {"mode": self.mode}
        if path == "/admin/reset" and method == "POST":
            self.reset()
            return 200, {"reset": True}
        if self.mode == "down":
            return 503, {"error": "vendor verification unavailable (simulated)"}
        if self.mode == "timeout":
            time.sleep(self.timeout_delay)
        if self.mode == "flaky":
            self.calls += 1
            if self.calls <= self.fail_n:
                return 503, {"error": "temporarily unavailable (simulated)"}
        if path == "/health" and method == "GET":
            return 200, {"status": "ok", "vendors": len(self.records)}
        if path == "/verify" and method == "POST":
            return self._verify(body)
        return 404, {"error": "not found"}

    def _verify(self, body: dict) -> tuple[int, dict]:
        tax_id = body.get("tax_id")
        if not isinstance(tax_id, str) or not tax_id.strip():
            return 422, {"error": "tax_id is required"}
        self.seq += 1
        bank = body.get("bank_account")
        rec = self.records.get(tax_id)
        if not re.fullmatch(TAX_ID_REGEX, tax_id):
            tax_status = "INVALID_FORMAT"
        elif rec is None:
            tax_status = "NOT_FOUND"
        else:
            tax_status = "REJECTED" if rec.get("verification_status") == "REJECTED" or self.mode == "reject_all" else "VERIFIED"
        bank_status = "NOT_PROVIDED" if not bank else ("MATCH" if rec and rec.get("bank_account") == bank else "MISMATCH")
        if tax_status == "VERIFIED":
            status = "REJECTED" if bank_status == "MISMATCH" else "VERIFIED"
        else:
            status = {"REJECTED": "REJECTED", "NOT_FOUND": "NOT_FOUND", "INVALID_FORMAT": "INVALID"}[tax_status]
        return 200, {"request_id": f"VV-{self.seq:06d}", "status": status, "tax_id_status": tax_status, "bank_status": bank_status,
                     "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
