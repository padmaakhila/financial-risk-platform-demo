# Software Requirements Specification (SRS)

Identifiers are used by `docs/TRACEABILITY.md` and the tests.

## 1. System overview
Streamlit UI -> FastAPI -> SQLAlchemy (SQLite default) ; worker process with a database job queue ; workflow with allowlisted tools ; Ollama or template for explanations ; mock ERP and vendor APIs. See `docs/ARCHITECTURE.md`.

## 2. Functional requirements
**Authentication and authorization**
- FR-AUTH-1 Users sign in with username/password; JWT expires (default 30 min); logout revokes the token.
- FR-AUTH-2 Roles: admin, reviewer, ap_clerk, auditor. Every protected endpoint checks the role; Streamlit pages hide what the role cannot use.
- FR-AUTH-3 Repeated failed logins are throttled; failures and denials are audited.

**Upload and documents**
- FR-UP-1 Accept PDF, PNG, JPG (invoice/PO/GRN) and CSV (vendor records); validate extension, MIME, signature, size, name.
- FR-UP-2 Store files under server-generated names in a controlled folder; no path traversal; evidence retrieval is access-controlled.
- FR-UP-3 Track document status and background job progress; the UI never blocks on processing.

**Classification and extraction**
- FR-EX-1 Classify invoice / PO / GRN / vendor record (ML + rules fallback); detect digital vs scanned.
- FR-EX-2 Extract header, line items, taxes, totals, bank and tax identifiers, with per-field confidence, source snippet, page and location.
- FR-EX-3 Validate with Pydantic; retry OCR once with another configuration; otherwise mark manual entry.
- FR-EX-4 LLM-supplied values are accepted only if they appear in the document text and carry no calibrated confidence.

**Deterministic checks**
- FR-CHK-1 Recalculate line totals, subtotal, tax and grand total with Decimal and half-up rounding.
- FR-CHK-2 Two-way (invoice-PO) and three-way (invoice-PO-GRN) matching with configurable tolerances.
- FR-CHK-3 Exact and fuzzy duplicate detection; store signals, score, threshold, related invoice.
- FR-CHK-4 Validate tax-ID and bank formats, mandatory fields, and scan document text for instruction-like content.
- FR-CHK-5 One exception record per issue with type, severity (fixed table), expected, actual, difference, rule id, evidence, status, timestamp.

**AI**
- FR-AI-1 Explain stored findings only; structured JSON output citing finding ids.
- FR-AI-2 Verify numbers, citations and coverage; max 2 retries; per-call timeout; template fallback; label model vs template.
- FR-AI-3 Audit Summary Agent summarises saved events; raw timeline always available.
- FR-AI-4 External LLM API disabled unless explicitly configured; PII redacted before prompts.

**Review, payment, audit**
- FR-REV-1 Review queue with evidence; approve, reject, request documents; comments; idempotent decisions.
- FR-REV-2 Backend rejects decisions from wrong roles, wrong states and duplicate submissions.
- FR-PAY-1 Mock ERP payment only after a recorded approval; idempotent; outage leaves the invoice pending.
- FR-AUD-1 Every state change and approval writes an audit event (actor, time, action, decision, tool result) in a hash chain.

**Reporting and monitoring**
- FR-REP-1 Dashboards: totals, pending reviews, duplicates, discrepancies by type/severity, aging, job and AI metrics.
- FR-REP-2 Reconciliation report as CSV and PDF; totals equal the database.
- FR-MON-1 Job failures, p50/p95 latency, error rate, AI availability/usage, integration health, audit-chain verification.

**Administration and integrations**
- FR-ADM-1 Manage users/roles, matching tolerances (validated, audited), simulate outages of the mocks.
- FR-INT-1 Mock ERP payment API (idempotency, outage simulation). FR-INT-2 Mock vendor verification API (success, rejection, unavailable, timeout, flaky).

**Data**
- FR-DAT-1 Deterministic synthetic dataset: 520 invoices, 24 scenarios with stored ground truth; scripts to generate, seed, reset, render PDFs/scans.

## 3. Non-functional requirements
- NFR-1 Security: see `docs/SECURITY.md`. NFR-2 Reliability: bounded retries, timeouts, safe errors, recovery of interrupted jobs, no success reported after failure.
- NFR-3 Performance: deterministic checks in milliseconds per invoice; explanation latency depends on the model (reported, not promised).
- NFR-4 Free-first: SQLite, optional Ollama, no paid service required. NFR-5 Observability: structured JSON logs without secrets, metrics endpoint, audit trail.
- NFR-6 Maintainability: pure-Python services separated from adapters; tests for each layer. NFR-7 Portability: Windows first, Linux (AWS/Docker) supported.

## 4. Interfaces
HTTP API documented by OpenAPI (`/docs`, `docs/openapi.json` via `scripts/export_openapi.py`) and `docs/postman_collection.json`. Mock ERP: `POST /payments` with `Idempotency-Key`. Mock vendor service: `POST /verify`. Schemas are in `docs/API_EXAMPLES.md`.

## 5. Constraints
Streamlit only for the UI; FastAPI + Pydantic + SQLAlchemy; no PostgreSQL or paid managed service without approval; synthetic data only.
