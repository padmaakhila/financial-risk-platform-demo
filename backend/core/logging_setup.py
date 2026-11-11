"""Structured JSON logging with secret/PII redaction. Never log passwords, tokens, API keys, bank details or tax IDs."""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone

from backend.services.redaction import redact_text

_SECRET_RE = re.compile(r"(?i)(bearer\s+[A-Za-z0-9._~+/=-]+|(password|passwd|secret|api[_-]?key|token|authorization)\s*[=:]\s*\S+)")
EXTRA_FIELDS = ("request_id", "method", "path", "status", "duration_ms", "user", "job_id", "invoice_id", "node", "tool")


def scrub(text: str) -> str:
    return redact_text(_SECRET_RE.sub("[SECRET]", text))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "level": record.levelname, "logger": record.name,
               "msg": scrub(record.getMessage())}
        for k in EXTRA_FIELDS:
            if hasattr(record, k):
                out[k] = getattr(record, k)
        if record.exc_info:
            out["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            out["stack"] = scrub(self.formatException(record.exc_info))[-1500:]
        return json.dumps(out, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
