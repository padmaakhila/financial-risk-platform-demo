"""One error envelope for every failure: {"error": {"code", "message", "request_id", "details"?}}. No stack traces, no echoed input."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.core.errors import NotFound
from backend.integrations.clients import IntegrationRejected, IntegrationUnavailable
from backend.services.payments import ApprovalRequired, PaymentError
from backend.services.review import Conflict, InvalidState, PermissionDenied, ValidationFailed
from backend.services.state_machine import InvalidTransition
from backend.services.upload_validation import UploadError

log = logging.getLogger("api")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def _body(request: Request, code: str, message: str, details=None) -> dict:
    err = {"code": code, "message": message, "request_id": getattr(request.state, "request_id", None)}
    if details:
        err["details"] = details
    return {"error": err}


def register_handlers(app: FastAPI) -> None:
    def make(status: int, code: str | None = None):
        async def handler(request: Request, exc: Exception):
            return JSONResponse(_body(request, code or getattr(exc, "code", "ERROR"), str(getattr(exc, "message", None) or exc)), status_code=status)
        return handler

    app.add_exception_handler(PermissionDenied, make(403, "FORBIDDEN"))
    app.add_exception_handler(InvalidState, make(409, "INVALID_STATE"))
    app.add_exception_handler(InvalidTransition, make(409, "INVALID_STATE"))
    app.add_exception_handler(Conflict, make(409, "CONFLICT"))
    app.add_exception_handler(ApprovalRequired, make(409, "APPROVAL_REQUIRED"))
    app.add_exception_handler(ValidationFailed, make(422, "VALIDATION_FAILED"))
    app.add_exception_handler(NotFound, make(404, "NOT_FOUND"))

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return JSONResponse(_body(request, exc.code, exc.message, exc.details), status_code=exc.status,
                            headers={"WWW-Authenticate": "Bearer"} if exc.status == 401 else None)

    @app.exception_handler(UploadError)
    async def upload_error(request: Request, exc: UploadError):
        return JSONResponse(_body(request, exc.code, exc.message), status_code=exc.http_status)

    @app.exception_handler(PaymentError)
    async def payment_error(request: Request, exc: PaymentError):
        return JSONResponse(_body(request, "PAYMENT_REJECTED", str(exc)), status_code=502)

    @app.exception_handler(IntegrationUnavailable)
    async def unavailable(request: Request, exc: IntegrationUnavailable):
        return JSONResponse(_body(request, "INTEGRATION_UNAVAILABLE", "An external service is unavailable. Please retry later."), status_code=503)

    @app.exception_handler(IntegrationRejected)
    async def rejected(request: Request, exc: IntegrationRejected):
        return JSONResponse(_body(request, "INTEGRATION_REJECTED", "An external service rejected the request."), status_code=502)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError):
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]), "problem": e["type"]} for e in exc.errors()]
        return JSONResponse(_body(request, "INVALID_REQUEST", "The request is not valid. Check the listed fields.", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_exc(request: Request, exc: StarletteHTTPException):
        code = {401: "NOT_AUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(_body(request, code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        log.exception("unhandled error", extra={"request_id": getattr(request.state, "request_id", None), "path": request.url.path})
        return JSONResponse(_body(request, "INTERNAL_ERROR", "Something went wrong on the server. Quote the request id when reporting it."), status_code=500)
