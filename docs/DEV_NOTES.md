# Developer notes (build log by batch)

Status: **Batch 1 of 7 (foundation)**. Streamlit pages, FastAPI endpoints, agents and
integrations arrive in later batches. Nothing here uses real financial data.

## Windows setup (PowerShell, from the project folder)
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
pip install -r requirements.txt
copy .env.example .env                # then set SECRET_KEY (see comment inside)
python -m scripts.init_db             # creates data\app.db (SQLite) + default settings
python -m scripts.seed_database       # 520 invoices, POs, GRNs, ground truth, demo users
python -m scripts.generate_documents  # sample PDFs in data\documents
python -m pytest -q                   # run the tests
```
Reset the dev database (makes a backup first): `python -m scripts.reset_database --yes`

## Data design notes
- Same seed gives identical data (`--seed 42`). Standard library `random` is used, not Faker, so
  ground truth cannot drift between machines.
- Invoice rows hold the *intended structured values*; PDFs in `data/documents` are renderings used
  to test extraction. Ground truth (`scenario_ground_truth`) lists expected rule IDs per invoice.
- Duplicates always arrive after their original (higher `seq`); only the later invoice is flagged.
- Matching rules check line quantities/prices only; they do not re-report arithmetic errors, and
  cumulative over-billing across several invoices of one PO is not checked (documented limitation).
- SQLite limits: one writer at a time (WAL + 30 s busy timeout configured). The audit hash chain is
  tamper-evident, not immutable.

## Batch 2: Matching Service (deterministic, no LLM)
`backend/services/`: `arithmetic.py` (Decimal recalculation), `validation.py` (formats, mandatory
fields, prompt-injection scan), `po_matching.py` (two-way / three-way), `duplicates.py` (exact + weighted
fuzzy score), `matching.py` (entry point), `matching_db.py` (loads records, stores exceptions + audit event).
- Tolerances live in the `settings` table (editable on the future Admin page).
- Severity is a fixed table in `rules.py`; results are `pass`, `warning` or `fail`.
- Rules checked against the 520-invoice ground truth in `tests/test_matching.py`.
- Limits: injection detection is pattern-based (can be evaded); duplicate scoring uses RapidFuzz when
  installed, otherwise difflib (scores differ slightly); no cumulative over-billing check across invoices.

## Batch 3: upload validation, classification, Extraction Agent
- `services/upload_validation.py`: extension allow-list, size, MIME vs extension, file signature, PDF end marker,
  CSV sanity, filename sanitising, server-generated storage names, path-traversal-safe lookup.
- `services/classifier.py`: TF-IDF + logistic regression (trained on synthetic text) with keyword rules as fallback;
  `make_plan()` builds the per-document workflow plan.
- `services/extraction.py`: pdfplumber for text PDFs; Tesseract for scans/images with one retry using an alternative
  configuration; schema validation via `schemas/extraction.py` (Pydantic); optional LLM mapping whose values are
  accepted only if they literally appear in the source text.
- Confidence: text-layer PDFs = 1.0 (`pdf_text`); OCR = mean word confidence (`ocr_word_conf`); LLM-supplied = none.
  Below 0.70 => `DOC_LOW_CONF` warning; below 0.40 or under 15 words => `DOC_UNREADABLE` and manual entry.
- `services/extraction_db.py` stores documents, extracted fields (with page, snippet, bounding box), invoices, POs/GRNs/vendors.

### Optional: install Tesseract on Windows
Install the Windows build of Tesseract (for example the UB Mannheim installer), then either add its folder to PATH or set
`TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe` in `.env`. Without it the app still runs: digital PDFs work,
scanned files are marked "needs manual entry" with a clear message.
Known limits: the rule parser reads this project's synthetic layouts; real-world invoices need new patterns or the LLM
mapper. Heavily garbled OCR usually ends in manual entry, which is the intended safe outcome.

## Batch 4: LLM layer, agents, workflow, mock integrations
**Run the two mock services (two extra PowerShell windows, venv activated):**
```powershell
uvicorn backend.integrations.erp_mock_app:app --port 8101      # docs: http://localhost:8101/docs
uvicorn backend.integrations.vendor_mock_app:app --port 8102   # docs: http://localhost:8102/docs
# no-FastAPI alternative:  python -m backend.integrations.mock_server erp --port 8101
```
Simulate failures: `POST /admin/simulate {"mode":"down"|"timeout"|"flaky"|"reject_all","fail_n":2}`, reset with `POST /admin/reset`.

**LLM (optional).** Install Ollama for Windows, then `ollama pull qwen2.5:1.5b` (about 1 GB; suits 8 GB RAM, CPU only, slow but usable)
or `llama3.2:3b` (about 2 GB, better wording, slower). With no Ollama the app uses labelled template explanations.
An external API stays OFF unless `LLM_PROVIDER=api` AND `LLM_API_ENABLED=true` AND URL/key/model are set; it would send
redacted text to a third party and may cost money.

**What is where**
- `agents/llm.py` providers + hard deadline; `agents/risk_explainer.py` prompt, schema, verification, template, retries;
  `agents/audit_summarizer.py`; `agents/tools.py` allowlist; `agents/workflow.py` nodes, router, runner, LangGraph wiring;
  `agents/workflow_db.py` database tools.
- `services/review.py` human decisions; `services/payments.py` the only path to the ERP (approval-gated, idempotent);
  `services/state_machine.py` legal status changes; `integrations/` mocks + clients; `services/redaction.py`.
- Verification rejects: unknown finding ids, numbers not in the cited finding, fake page citations, unexplained medium+
  findings, approve/pay instructions. Timeouts/outages go straight to the template; bad output gets at most 2 retries.
- Not guaranteed: wording quality of a small local model; the verifier checks facts and numbers, not tone.

## Batch 5: API, worker, reports
**Start everything (each in its own PowerShell window, venv activated, project root):**
```powershell
python -m scripts.init_db ; python -m scripts.seed_database        # once
uvicorn backend.integrations.erp_mock_app:app --port 8101          # 1  mock ERP
uvicorn backend.integrations.vendor_mock_app:app --port 8102       # 2  mock vendor verification
uvicorn backend.main:create_app --factory --port 8000              # 3  API   -> http://localhost:8000/docs
python -m backend.workers.worker                                   # 4  worker (extraction + workflow jobs)
```
Quick check: open http://localhost:8000/api/health, then use **Authorize** in `/docs` after `POST /api/auth/login`.

**Endpoints** (all need a Bearer JWT except `/api/health` and `/api/auth/login`):
auth (`/api/auth/login|me|logout`), documents (`POST /api/documents`, `GET /api/documents[/id[/file]]`, `GET /api/jobs/{id}`),
invoices (`GET /api/invoices[/id]`, `POST .../process`, `GET .../events`, `POST .../audit-summary`), records
(`/api/vendors|purchase-orders|goods-receipts`), review (`GET /api/review/queue`, `POST /api/invoices/{id}/decision`,
`POST /api/invoices/{id}/payment`), reports (`/api/reports/summary|reconciliation[.csv|.pdf]`), admin (`/api/admin/users|settings|integrations`),
monitoring (`/api/monitoring/metrics`, `/api/audit/verify|events`).

**Roles:** admin (everything), reviewer (decide, pay, queue, vendor CSV import), ap_clerk (upload, process, view own documents; bank details masked),
auditor (read-only: records, reports, audit, monitoring). One table: `backend/auth/permissions.py`. Roles are read from the database on every
request, so a demotion takes effect immediately. Denied attempts are written to the audit trail.

**Design notes and limits**
- Errors always use `{"error": {"code", "message", "request_id"}}`; validation errors never echo submitted values; money is returned as strings.
- The job queue is a database table (no Redis/Celery). Claims are atomic, retries back off (10 s, 20 s, ... max 5 min), a worker that dies is
  detected by heartbeat (5 min) and its job is re-queued; exhausted jobs end as FAILED and the invoice becomes FAILED. SQLite allows one writer
  at a time, so run ONE worker process locally.
- Login throttling and token revocation are kept in API process memory (lost on restart, not shared between several API processes).
- Uploaded files are written before the database commit; a crash in between could leave an orphan file (harmless, never served).
- PO/GRN documents are imported from PDFs; only vendor records can be imported from CSV.

## Batch 6: Streamlit application
```powershell
streamlit run app.py        # 5th window; opens http://localhost:8501 (API, worker and the two mocks must be running)
```
Pages: Sign in, Dashboard, Document Upload, Business Records, AI / Agent Workflow, Review & Approval, Reports, Administration, Monitoring.
The sidebar only lists pages your role may use (a convenience); the API enforces permissions on every call and the pages show friendly
messages for 401/403/409 and for an unreachable API. Session state holds only the login token, name/role and form keys.

- `ui/api_client.py` HTTP client (standard library), `ui/format.py` presentation helpers, `ui/components.py` shared panels, `ui/state.py` session glue.
- PDF previews are rendered to PNG on the server side of the UI process (no embedded HTML/JS). Long jobs run in the worker; the upload page polls
  the job and stays usable. Downloads (CSV/PDF) come from the API and are logged in the audit trail.
- `BACKEND_URL` in `.env` points the UI at the API (default http://localhost:8000).
- Tests: `tests/test_ui_pages.py` runs every page script against a stub of `streamlit` and a fake API that follows the real contract. It checks
  page logic and messages, not browser rendering. Please click through each page once yourself; layout issues cannot be seen by these tests.
