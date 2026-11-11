"""Clients for the two integrations: timeouts, bounded retries, typed failures, no secrets in errors."""
from __future__ import annotations

import time

from backend.core.http import HttpError, HttpStatusError, http_json, with_retries


class IntegrationUnavailable(Exception):
    """Service down / timed out after bounded retries (retryable later)."""

    def __init__(self, message: str, attempts: int = 1):
        super().__init__(message)
        self.attempts = attempts


class IntegrationRejected(Exception):
    """Service answered but refused the request (do not retry blindly)."""

    def __init__(self, status: int, body: dict):
        super().__init__(f"rejected with HTTP {status}")
        self.status, self.body = status, body


class _Base:
    def __init__(self, base_url: str, timeout: float = 5.0, max_retries: int = 2, sleep=time.sleep, backoff: float = 0.3):
        self.base_url, self.timeout, self.max_retries, self.sleep, self.backoff = base_url.rstrip("/"), timeout, max_retries, sleep, backoff

    def _call(self, method, path, payload=None, headers=None) -> dict:
        try:
            (status, data), attempts = with_retries(lambda: http_json(method, self.base_url + path, payload, timeout=self.timeout, headers=headers),
                                                    max_retries=self.max_retries, backoff=self.backoff, sleep=self.sleep)
        except HttpStatusError as e:
            if e.retryable:
                raise IntegrationUnavailable(f"HTTP {e.status}", getattr(e, "attempts", 1)) from None
            raise IntegrationRejected(e.status, e.body) from None
        except HttpError as e:
            raise IntegrationUnavailable(type(e).__name__, getattr(e, "attempts", 1)) from None
        return {**data, "_attempts": attempts, "_http_status": status}

    def healthy(self) -> bool:
        try:
            http_json("GET", self.base_url + "/health", timeout=2)
            return True
        except HttpError:
            return False


class VendorVerificationClient(_Base):
    def verify(self, *, tax_id: str, bank_account: str | None = None, vendor_code: str | None = None) -> dict:
        return self._call("POST", "/verify", {"tax_id": tax_id, "bank_account": bank_account, "vendor_code": vendor_code})


class ErpClient(_Base):
    def post_payment(self, payload: dict, idempotency_key: str) -> dict:
        return self._call("POST", "/payments", payload, {"Idempotency-Key": idempotency_key})
