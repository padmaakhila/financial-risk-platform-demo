"""FastAPI application factory.
Run:  uvicorn backend.main:create_app --factory --port 8000      (OpenAPI docs: http://localhost:8000/docs)"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from ap_copilot.router import router as copilot_router
from fastapi import FastAPI, Request

from backend.agents.llm import build_provider
from backend.api import routes_core, routes_ops
from backend.api.errors import register_handlers
from backend.auth.throttle import LoginThrottle, RevokedTokens
from backend.core.config import get_settings
from backend.core.logging_setup import setup_logging
from backend.core.metrics import RequestMetrics
from backend.integrations.clients import ErpClient, VendorVerificationClient

log = logging.getLogger("api")

TAGS = [{"name": n, "description": d} for n, d in [
    ("auth", "Login, logout, current user"), ("documents", "Upload, evidence retrieval, job status"), ("invoices", "Invoice list/detail, processing, audit summary"),
    ("records", "Vendors, purchase orders, goods receipts"), ("review", "Review queue, human decisions, payment release"),
    ("reports", "Dashboards and reconciliation exports"), ("admin", "Users, settings, integrations"), ("monitoring", "Metrics and audit trail"), ("health", "Liveness")]]


def create_app(settings=None, session_factory=None, erp_client=None, vendor_client=None, provider=None) -> FastAPI:
    settings = settings or get_settings()
    own_db = session_factory is None
    if own_db:
        from backend.database.session import get_session_factory
        session_factory = get_session_factory()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if own_db:
            from scripts.init_db import init_db
            init_db()
        yield

    app = FastAPI(title="Financial Document & Risk Analysis Platform API", version="1.0.0", openapi_tags=TAGS, lifespan=lifespan,
                  description="Synthetic-data Accounts Payable platform. All endpoints except /api/health and /api/auth/login require a Bearer JWT; "
                              "roles are enforced on every endpoint. Money values are strings (exact decimals).")
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.erp_client = erp_client or ErpClient(settings.erp_mock_url)
    app.state.vendor_client = vendor_client or VendorVerificationClient(settings.vendor_mock_url)
    app.state.provider = provider or build_provider(settings)
    app.state.throttle, app.state.revoked, app.state.req_metrics = LoginThrottle(), RevokedTokens(), RequestMetrics()
    setup_logging(settings.log_level)
    register_handlers(app)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("X-Request-ID", "")[:40] or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        start = time.perf_counter()
        response = await call_next(request)
        ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        app.state.req_metrics.record(request.url.path, response.status_code, ms)
        log.info("request", extra={"request_id": rid, "method": request.method, "path": request.url.path, "status": response.status_code,
                                   "duration_ms": ms, "user": getattr(request.state, "user", None)})
        return response

    for router in (routes_core.auth, routes_core.docs, routes_core.invoices, routes_core.records, routes_ops.review, routes_ops.reports,
                   routes_ops.admin, routes_ops.monitoring, routes_ops.health, copilot_router):
        app.include_router(router)
    return app
