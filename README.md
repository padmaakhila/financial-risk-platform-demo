<<<<<<< HEAD
# Financial Document & Risk Analysis Platform

A web portal for **Accounts Payable**: upload invoices, POs and goods-received notes; extract the data; **recalculate and match with deterministic code**; flag duplicates and discrepancies; get **plain-language explanations tied to the original evidence**; let a **human approve, reject or request documents**; pay through a mock ERP only after a recorded approval; keep a **hash-chained audit trail**; see dashboards and download reports.

It is a finance portal, **not a chatbot**. The AI (local Ollama, optional) only explains findings that code already stored, and code verifies every number and citation it writes. If the AI is missing, slow or wrong, the app falls back to labelled templates and keeps working. All data is **synthetic**.

Stack: Streamlit (only UI) | FastAPI + Pydantic + SQLAlchemy | SQLite (default; SQL Server Express optional; no PostgreSQL) | pdfplumber, Tesseract, scikit-learn, RapidFuzz, Decimal | LangGraph-ready workflow | mock ERP and vendor-verification services.

## Honest status (read first)
| Area | Status |
|---|---|
| Matching, arithmetic, duplicates, extraction, classifier, upload validation, agents, workflow logic, integrations, queue helpers, reports, UI helpers and all page scripts | Written **and executed in the build sandbox** (162 tests passed, including real Tesseract OCR and real HTTP against the mock services). |
| FastAPI app, SQLAlchemy models/services, worker, DB-backed tests, real Pydantic validation, Streamlit in a real browser, LangGraph wiring, Docker, AWS | Written and syntax-checked, but **could not be run in the build sandbox** (those packages/tools were not installable there). Run `python -m pytest -q` on your machine and send failures back: the first run will probably find a few bugs. |
| Evaluation | `reports/evaluation_report_pure_mode_sandbox.md` is a real measured run (520/520 invoices matched ground truth, p50 0.7 ms, p95 1.3 ms, matching + template explanation). Full-mode, model and AWS numbers are **not** claimed: run `python -m scripts.run_evaluation --with-tests`. |
| AWS | Guide written from current AWS documentation and announcements; **nothing was deployed**. Costs must be verified in your own Billing console. |

## Quick start (Windows, PowerShell, from the project folder)
Full beginner guide: `docs/WINDOWS_SETUP.md`. Troubleshooting: `docs/TROUBLESHOOTING.md`.
```powershell
py -3.11 -m venv .venv ; .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip ; pip install -r requirements.txt
copy .env.example .env          # then put a random value after SECRET_KEY=
python -m scripts.init_db ; python -m scripts.seed_database ; python -m scripts.make_demo_documents
python -m pytest -q
```
Start five processes (one terminal each, venv activated):
```powershell
uvicorn backend.integrations.erp_mock_app:app --port 8101
uvicorn backend.integrations.vendor_
mock_app:app --port 8102
uvicorn backend.main:create_app --factory --port 8000     # API docs: http://localhost:8000/docs
python -m backend.workers.worker
streamlit run app.py                                      # http://localhost:8501
```
Demo logins are printed by the seed script (development only). Optional: Tesseract (scans) and Ollama (AI explanations); both are explained in the setup guide and the app runs without them.

## Roles
admin (everything) | reviewer (queue, decisions, payments, vendor CSV import) | ap_clerk (upload, process, own documents, masked bank data) | auditor (read-only records, reports, audit, monitoring). Enforced by the API on every request; the UI only hides pages as a convenience.

## Project map
```
app.py, pages/        Streamlit app (9 pages)        ui/            API client, formatting, shared panels
backend/main.py       FastAPI factory                backend/api/   routers, errors, dependencies, views
backend/services/     arithmetic, matching, duplicates, extraction, classifier, review, payments, reports, audit, state machine
backend/agents/       LLM providers, risk explainer, audit summarizer, tool allowlist, workflow (+ LangGraph wiring)
backend/integrations/ mock ERP, mock vendor verification, clients      backend/workers/  job queue, worker, handlers
backend/models/       SQLAlchemy models              migrations/    Alembic baseline
scripts/              generate_data, seed, reset, init_db, create_admin, generate_documents, make_demo_documents,
                      run_evaluation, make_postman, export_openapi
tests/                pytest suite (+ stub streamlit and fake API for page tests)
docs/                 BRD, SRS, user stories, traceability, architecture (diagrams), agents, security, setup, troubleshooting,
                      SQL Server, API examples, Postman collection, demo script, evaluation report, dev notes
deployment/aws/       cost-first AWS guide, cleanup checklist, systemd units, backup/restore/health scripts
Dockerfile, docker-compose.yml, .github/workflows/ci.yml
```

## Key design rules
1. Deterministic code decides every financial fact (Decimal, half-up rounding, tolerances in the database).
2. The LLM has **no tools**; its output is verified (cited ids, numbers, pages, coverage, no payment instructions); max 2 retries, then template.
3. No payment without a recorded human approval; idempotency keys on decisions and payments; outages leave invoices pending, never paid.
4. Uploaded text is data, never instructions; PII redacted before prompts; secrets only in environment variables.
5. Audit events are append-only with a SHA-256 chain: **tamper-evident, not immutable**.

## Known limits
Synthetic data and rule parsers tuned to this project's document layouts; mock integrations only; SQLite = one writer (run one worker); login throttling in process memory; cumulative over-billing across several invoices on one PO is not checked; local small models are slow on an 8 GB CPU laptop. More in `docs/SECURITY.md` and `docs/BRD.md`.


uvicorn backend.main:create_app --factory --port 8000
python -m backend.workers.worker
streamlit run app.py
uvicorn backend.integrations.erp_mock_app:app --port 8101
uvicorn backend.integrations.vendor_
mock_app:app --port 8102
uvicorn backend.main:create_app --factory --port 8000     # API docs: http://localhost:8000/docs
python -m backend.workers.worker
streamlit run app.py                                      # http://localhost:8501
=======
# financial-risk-platform-demo
Financial Document and Risk Analysis Platform – Demo
>>>>>>> 230c5de853eff935538218d3cbc736b7c77c0e3e
