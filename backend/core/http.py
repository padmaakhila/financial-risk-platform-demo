"""Tiny JSON-over-HTTP client (standard library) with typed, retry-aware errors."""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Callable


class HttpError(Exception):
    retryable = False


class HttpTimeout(HttpError):
    retryable = True


class HttpUnavailable(HttpError):
    retryable = True


class HttpStatusError(HttpError):
    def __init__(self, status: int, body):
        super().__init__(f"HTTP {status}")
        self.status, self.body = status, body
        self.retryable = status in (408, 429)


def http_json(method: str, url: str, payload: dict | None = None, *, timeout: float = 10, headers: dict | None = None):
    """Return (status, parsed_json). 5xx 502/503/504 -> HttpUnavailable; other >=400 -> HttpStatusError."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        if e.code in (500, 502, 503, 504):
            raise HttpUnavailable(f"HTTP {e.code}") from None
        raise HttpStatusError(e.code, body) from None
    except (socket.timeout, TimeoutError):
        raise HttpTimeout("request timed out") from None
    except urllib.error.URLError as e:
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            raise HttpTimeout("request timed out") from None
        raise HttpUnavailable(f"cannot connect: {type(e.reason).__name__}") from None
    except (ConnectionError, OSError) as e:
        raise HttpUnavailable(f"network error: {type(e).__name__}") from None


def with_retries(fn: Callable, *, max_retries: int = 2, backoff: float = 0.3, sleep: Callable = time.sleep):
    """Retry ONLY retryable HttpErrors, at most max_retries extra attempts. Returns (result, attempts)."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn(), attempt
        except HttpError as exc:
            if not exc.retryable or attempt > max_retries:
                exc.attempts = attempt  # type: ignore[attr-defined]
                raise
            sleep(backoff * 2 ** (attempt - 1))
