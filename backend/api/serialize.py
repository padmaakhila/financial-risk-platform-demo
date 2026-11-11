"""JSON serialisation that never turns money into floats (Decimal -> string)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi.responses import JSONResponse


def ser(o):
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, dict):
        return {k: ser(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [ser(v) for v in o]
    return o


def ok(data, status: int = 200) -> JSONResponse:
    return JSONResponse(ser(data), status_code=status)
