"""Mock ERP payment API (core logic, framework-free). NEVER connects to a real bank or ERP.

POST /payments   headers: Idempotency-Key  body: {invoice_number, vendor_code, amount (STRING), currency, approval_id}
  201 created | 200 replay of the same key+body | 400 missing key | 409 key reuse with different body or duplicate approval
  422 invalid body | 503 simulated outage
GET  /health, GET /payments/{id}, POST /admin/simulate {"mode": normal|down|timeout|flaky, "fail_n": 2}, POST /admin/reset"""
from __future__ import annotations

import threading
import time
from decimal import Decimal, InvalidOperation

REQUIRED = ("invoice_number", "vendor_code", "amount", "currency", "approval_id")


class ErpMock:
    def __init__(self, timeout_delay: float = 5.0):
        self.timeout_delay = timeout_delay
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        self.mode, self.fail_n, self.calls = "normal", 0, 0
        self.payments: dict[str, dict] = {}
        self.by_key: dict[str, tuple[dict, str]] = {}
        self.by_approval: dict[str, str] = {}

    def handle(self, method: str, path: str, headers: dict, body: dict | None) -> tuple[int, dict]:
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        body = body or {}
        if path == "/admin/simulate" and method == "POST":
            mode = body.get("mode", "normal")
            if mode not in ("normal", "down", "timeout", "flaky"):
                return 422, {"error": "mode must be normal, down, timeout or flaky"}
            self.mode, self.fail_n, self.calls = mode, int(body.get("fail_n", 2)), 0
            return 200, {"mode": self.mode}
        if path == "/admin/reset" and method == "POST":
            self.reset()
            return 200, {"reset": True}
        if self.mode == "down":
            return 503, {"error": "ERP unavailable (simulated)"}
        if self.mode == "timeout":
            time.sleep(self.timeout_delay)
        if self.mode == "flaky":
            self.calls += 1
            if self.calls <= self.fail_n:
                return 503, {"error": "ERP temporarily unavailable (simulated)"}
        if path == "/health" and method == "GET":
            return 200, {"status": "ok", "payments": len(self.payments)}
        if path.startswith("/payments/") and method == "GET":
            p = self.payments.get(path.rsplit("/", 1)[1])
            return (200, p) if p else (404, {"error": "payment not found"})
        if path == "/payments" and method == "POST":
            return self._create(headers.get("idempotency-key"), body)
        return 404, {"error": "not found"}

    def _create(self, key, body) -> tuple[int, dict]:
        if not key or not key.strip():
            return 400, {"error": "Idempotency-Key header is required"}
        missing = [f for f in REQUIRED if body.get(f) in (None, "")]
        if missing:
            return 422, {"error": f"missing fields: {missing}"}
        if not isinstance(body["amount"], str):
            return 422, {"error": "amount must be a decimal string"}
        try:
            amount = Decimal(body["amount"])
        except InvalidOperation:
            return 422, {"error": "amount is not a number"}
        if not amount.is_finite() or amount <= 0:
            return 422, {"error": "amount must be greater than zero"}
        if not (isinstance(body["currency"], str) and len(body["currency"]) == 3 and body["currency"].isupper()):
            return 422, {"error": "currency must be a 3-letter code"}
        fingerprint = "|".join(str(body[f]) for f in REQUIRED)
        with self._lock:
            if key in self.by_key:
                payment, fp = self.by_key[key]
                if fp != fingerprint:
                    return 409, {"error": "Idempotency-Key was already used with a different request"}
                return 200, {**payment, "replayed": True}
            approval = str(body["approval_id"])
            if approval in self.by_approval:
                return 409, {"error": "a payment for this approval already exists", "payment_id": self.by_approval[approval]}
            pid = f"PAY-{len(self.payments) + 1:06d}"
            payment = {"payment_id": pid, "status": "POSTED", "invoice_number": body["invoice_number"], "vendor_code": body["vendor_code"],
                       "amount": str(amount), "currency": body["currency"], "approval_id": approval, "replayed": False}
            self.payments[pid], self.by_key[key], self.by_approval[approval] = payment, (payment, fingerprint), pid
            return 201, payment
