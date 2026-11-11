# Requirement traceability matrix

Sources: the assignment PDF (`04_Financial_Document_and_Risk_Analysis_Platform.pdf`, section numbers 01-11), the flowchart PDF (`AP_Risk_Platform_Project_Flowchart.pdf`, pages 1-8) and the master prompt.

| # | Requirement (source) | Implementation | Tests |
|---|---|---|---|
| 1 | Upload scanned/digital invoices, POs, receipts, vendor records (01, flow p2) | `routes_core.upload_document`, `upload_validation.py`, `csv_import.py` | `test_upload_validation`, `test_api` |
| 2 | Extract header, lines, taxes, totals, bank details into schema-validated fields (01) | `extraction.py`, `schemas/extraction.py` | `test_extraction`, `test_schemas` |
| 3 | Deterministic arithmetic, 2-/3-way matching (01) | `arithmetic.py`, `po_matching.py` | `test_matching` |
| 4 | Duplicate detection with fuzzy signals (01) | `duplicates.py` | `test_matching` |
| 5 | Exception records for quantity, price, tax, missing PO/GRN (01) | `matching_db.py`, `rules.py` | `test_matching`, `test_workflow_db` |
| 6 | LLM only explains traceable findings; snippets and confidence caveats (01) | `risk_explainer.py`, `components.findings_view` | `test_agents`, `test_ui_support` |
| 7 | Reviewer approve/reject/request documents, auditable (01) | `review.py`, `audit.py` | `test_review_payments`, `test_api` |
| 8 | Export reconciliation reports; aging, discrepancy, processing dashboards (01) | `reports.py`, `dashboard.py`, pages 2, 7 | `test_support_modules`, `test_api` |
| 9 | Four agents/services with defined tools, errors, hand-offs (03) | `docs/AGENTS.md`, `agents/`, `services/` | `test_agents`, `test_workflow` |
| 10 | Graph flow request > plan > tools > verify > response > audit; persisted state; retries; timeouts; allowlist (03, 07) | `agents/workflow.py`, `tools.py`, `workflow_db.py` | `test_workflow`, `test_workflow_db` |
| 11 | Document which steps are deterministic, ML, LLM (03, flow p6) | `docs/ARCHITECTURE.md` section 5 | review |
| 12 | Streamlit-only UI, login + role navigation, records, workflow, review queue, admin, monitoring (04) | `app.py`, `pages/`, `ui/` | `test_ui_pages` |
| 13 | Validation messages, progress states, previews, downloads (04) | `ui/format.py`, upload page | `test_ui_support`, `test_ui_pages` |
| 14 | 500+ synthetic invoices with seeded duplicates and calculation issues (05) | `scripts/generate_data.py` | `test_data_generator` |
| 15 | At least two functioning integrations (05) | `integrations/` (ERP, vendor verification) | `test_integrations` |
| 16 | Seed scripts, edge cases, reset instructions (05) | `scripts/seed_database.py`, `reset_database.py` | `test_database` |
| 17 | Background processing (06) | `workers/` | `test_worker` |
| 18 | RBAC on pages and endpoints (07) | `permissions.py`, `deps.py` | `test_api`, `test_ui_pages` |
| 19 | OpenAPI, Pydantic validation, migrations (07) | `main.py`, `schemas/`, `migrations/`, `scripts/export_openapi.py` | `test_api` |
| 20 | Redaction, prompt-injection defences, secrets in env (07) | `redaction.py`, `validation.py`, `config.py` | `test_redaction_llm`, `test_matching` |
| 21 | Structured logs, cost and latency metrics, error dashboards (07) | `logging_setup.py`, `metrics.py`, page 9 | `test_support_modules` |
| 22 | Unit, API, agent tool, failure tests, evaluation dataset (07) | `tests/`, `scripts/run_evaluation.py` | whole suite |
| 23 | Docker Compose, cloud deployment (07) | `Dockerfile`, `docker-compose.yml`, `deployment/aws/` | manual (not run in the build environment) |
| 24 | Audit trail with actor, time, tool result (07) | `audit.py` | `test_database`, `test_review_payments` |
| 25 | Known duplicates/mismatches identified; amounts recalculated; no unapproved payment; traceability (08) | evaluation report; `payments.py` | `test_matching`, `test_review_payments` |
| 26 | Demonstrate invalid input, outage, LLM timeout, retry/fallback (08) | `docs/DEMO_SCRIPT.md` | `test_api`, `test_integrations`, `test_workflow` |
| 27 | Measure p50/p95, error rate, tokens, cost per task (08) | `scripts/run_evaluation.py` | report |
| 28 | BRD/SRS, stories, diagrams, Postman, evaluation report, demo (09) | `docs/` | review |
| 29 | SQLite default, SQL Server Express optional, no PostgreSQL (prompt) | `database/session.py`, `docs/SQLSERVER_SETUP.md` | `test_database` |
| 30 | Ollama preferred, optional API off by default, template fallback (prompt) | `agents/llm.py` | `test_redaction_llm`, `test_agents` |
| 31 | LangGraph orchestration where practical (prompt, 06) | `agents/workflow.py::build_langgraph` (same nodes as the tested runner) | not executed in the build environment (langgraph not installable there) |
| 32 | Cost-checked AWS deployment and cleanup (prompt) | `deployment/aws/` | manual |

## Departures from the PDFs (deliberate)
- **PostgreSQL -> SQLite** (assignment allows "equivalent relational DB"; the prompt requires SQLite default). LangGraph checkpoints use SQLite (`langgraph-checkpoint-sqlite`) plus our own `workflow_checkpoints` table.
- **Celery + Redis -> database job table + worker process** (simplest reliable option, per the prompt).
- **Langfuse/LangSmith tracing -> own metrics tables** (`llm_usage`, `background_jobs`, `workflow_checkpoints`, audit events); optional external tracing can be added later.
