# ap_copilot — read-only AI Copilot for the Financial Risk Platform

An isolated add-on. It adds one API endpoint (`POST /api/copilot/chat`) and one Streamlit widget.
It changes no tables, no migrations, no existing business logic, and needs **no new packages**
(FastAPI, SQLAlchemy, Pydantic, Streamlit and your Ollama provider are reused).

## What it does
Answers questions about invoices, vendors, POs, GRNs, extraction/OCR results, risk findings,
workflow status, (permitted) audit history and report counts, using records retrieved from your
PostgreSQL database. Every answer has two parts:

1. **Recorded facts** – built deterministically from the retrieved rows (never by the model).
2. **AI explanation** – a short Ollama-written explanation, appended only if it passes validation.
   If Ollama is down / times out / returns junk, you still get the facts plus a clear notice.

It distinguishes: *reference stored on the invoice* / *reference from extraction* / *master record found* /
*what the platform's findings say*. It never says a PO or GRN is "matched" just because a number appears.

## Folder structure
```
ap_copilot/
  router.py          POST /api/copilot/chat (JWT + view_records, read-only)
  schemas.py         Pydantic models (v1/v2-compatible syntax)
  security.py        input validation, refusals (write/SQL/injection), permission Scope, read-only session guard
  guardrails.py      injection neutralising of retrieved text + validation of every model reply
  pii.py             redaction + mask_account reuse
  retrieval.py       bounded, permission-filtered retrieval LOGIC + PO/GRN match facts
  orm_repo.py        the only DB access: SELECT-only, existing models   (extra file: keeps logic testable without a DB)
  answer_service.py  facts renderer + guarded LLM call via existing provider
  prompts.py         system prompts (second line of defence only)
  streamlit_widget.py  render_copilot()
  config.py          static limits (no secrets, no URLs)
  tests/             139 passing here (see "Tests")
```

## Authentication & permissions
* Uses your existing JWT dependency: `Depends(require("view_records"))` and `Depends(get_session)`.
  No second login. The UI sends the token through the existing `ui.state.api()` client.
* `security.build_scope(role)` calls your `can()`; nothing is hard-coded except one rule name:
  the **AP-clerk ownership rule** (`role == "ap_clerk"`) from your `_visible_doc()` description.
* Filtering happens **before** retrieval/prompting – unauthorised data is not fetched:

| Data | Requires | Enforcement |
|---|---|---|
| invoice / vendor / PO / GRN rows | `view_records` | endpoint dependency + scope |
| extracted fields, source snippets, `source_evidence` | `view_evidence` (+ clerk owns the document) | repo method not called otherwise; snippet column not even SELECTed |
| audit events (action/actor/decision/time only) | `view_audit` | repo method not called otherwise |
| review decisions/comments | `view_queue` or `view_audit` | same |
| masked bank account | `view_bank_details` | omitted otherwise. Full numbers are **never** sent, even to admins |
| report counts | `view_reports` | not called otherwise |
| `Setting`, `User`, `AiOutput`, `WorkflowTrace`, `LlmUsage`, hashes, `tool_result`, `details` | – | not queried at all |

## Retrieval
Identifiers (invoice/PO/GRN numbers, vendor codes) are pulled from the question (+ "this invoice" context
sent by the UI). All queries are SELECT-only, parameterised, `LIMIT`-bounded (see `config.py`:
5 invoices, 2 with full detail, 20 findings, 40 fields, 10 audit rows…). Money stays as the stored
decimal text; nothing is converted to float. An identifier that matches nothing is reported as
"not found" only when the query succeeded; a DB failure returns "cannot retrieve live information".

## Ollama reuse
`request.app.state.provider` via your `call_with_deadline`. No new client, model name or URL.
The deadline is capped at 25 s (`COPILOT_MAX_LLM_SECONDS`) so the whole request fits inside the UI
`ApiClient` default 30 s timeout. `LLMTimeout` / `LLMUnavailable` / other errors / `NullProvider` /
empty or invalid replies all degrade to "facts only" with a notice. Exception text is never logged or returned.

## Prompt-injection handling (enforced in code)
* User questions that try to override rules, reveal prompts/secrets, run SQL/code/shell, or ask for an
  action (approve/reject/pay/edit…) are refused **before** any retrieval or model call.
* Every string from the DB/OCR (notes, vendor names, snippets, line text…) goes through
  `sanitize_untrusted`: control chars stripped, secrets/account numbers redacted, instruction-like
  phrases replaced, `<`/`>` and markdown link syntax broken (cannot forge the `<<<DATA … DATA>>>` fence), truncated.
* The model has no tools. Its reply is untrusted: rejected if empty, too long, leaking the prompt, containing
  secrets/links/HTML/code/JSON, claiming an action happened, recommending approve/pay, claiming "safe/no issues",
  or mentioning any identifier or number that is not in the retrieved data.

## PII
Bank values are masked with your `mask_account()` at the repo boundary and again in retrieval; fields whose
name looks bank-related are masked; JWTs, Bearer tokens, DB URLs, `password=`/`secret=` pairs, IBAN-like and
9–20-digit runs are redacted from anything placed in a prompt; no full document text is ever sent
(snippets ≤160 chars). Logs contain only request id, user id, mode, timing, counts, error category.

## Why read-only
The router has a single POST that only reads. `read_only_session()` (1) makes any ORM flush with new/changed/
deleted objects raise, (2) runs `SET LOCAL transaction_read_only = on` on PostgreSQL, (3) rolls back on exit.
No payment/review/audit/admin service or tool is imported (a test scans the source). It does not call
`/audit-summary` (which writes `AiOutput`). Chat history is not stored in PostgreSQL.

## Integration (two small edits; copy the folder first)
```cmd
cd /d C:\Data\financial-risk-plat\financial-risk-platfor\financial-risk-platfo
xcopy /E /I C:\path\to\ap_copilot ap_copilot
```
**1. `backend/main.py`** – add the import near the other router imports, and register it where the others are registered:
```python
from ap_copilot.router import router as copilot_router
...
app.include_router(copilot_router)      # next to the existing include_router(...) calls inside create_app
```
**2. `app.py`** – after `nav = st.navigation(pages)` and **before** `nav.run()` (pages that call `st.stop()` would otherwise skip it):
```python
from ap_copilot.streamlit_widget import render_copilot
...
nav = st.navigation(pages)
render_copilot()      # no-op when signed out or without view_records
nav.run()
```
Sign-out: the widget clears its conversation whenever there is no signed-in user or a different user id appears,
so `ui/state.py` needs no change.

## Run
```cmd
cd /d C:\Data\financial-risk-plat\financial-risk-platfor\financial-risk-platfo
.venv\Scripts\activate
python -m pytest ap_copilot\tests -q
```
Start the API and Streamlit exactly as you do today, sign in, and use **Ask AI Copilot** (bottom-right).
Make sure Ollama is running (`ollama list` should show your configured model).

## UI and limitations (not browser-tested by the author)
* Compact mode: a `st.popover` button, pinned bottom-right with CSS (`st-key-ap_copilot_fab`), opens the chat
  (welcome text, example questions, history, spinner, Clear, Expand). Expand opens a large `st.dialog`
  with the chat on the left and an **Investigation** panel on the right (invoice, findings, missing/low-confidence
  extraction, PO/GRN facts, verification steps, evidence refs), all taken from the last API response.
* It is **not** a custom-JS overlay or a true slide-in right drawer; the popover is anchored to the button.
  Requires a Streamlit with `st.popover` (≥1.31) and, for `container(key=…)` pinning, ≥1.39. Older versions fall
  back to an unpinned popover or a sidebar expander; without `st.dialog` the Expand button just keeps compact mode.
* Popover/dialog CSS selectors (`stPopoverBody`) can change between Streamlit releases.
* Each request is stateless (the model sees no earlier turns); "this invoice" works because the widget sends the last invoice number.
* A 1.5B model gives short explanations; the facts section is the authoritative part.
* Searching by vendor name works only with a quoted name (`"Acme"`) or vendor code.

## Assumptions to verify (I could not see your source)
1. `LLMResponse` exposes text as `.text/.content/.output/.response` (else treated as empty → facts only).
2. `ApiClient.post(path, json=…)` (falls back to positional body). Errors are matched by your `ApiProblem/Unauthorized/Unreachable`.
3. `Document` has an owner column named one of `uploaded_by, uploaded_by_id, uploader_id, owner_id, created_by, created_by_id, user_id`;
   otherwise clerks see **no extraction evidence** (fail closed). Edit `_OWNER_ATTRS` in `orm_repo.py` if yours differs.
4. PO/GRN line, `WorkflowCheckpoint` columns are copied only if they exist; tables have an integer `id`; `AuditEvent.entity_type`
   holds `"invoice"` and `entity_id` the invoice id; `ExceptionRecord.severity` uses `high`/`critical` for high risk.
5. `ui.state.user()` returns a dict with `role` and `id`/`username`.
Quick self-check inside your project: `python -m pytest ap_copilot\tests\test_read_only.py -q` – the last test compiles every
query against your real models on the PostgreSQL dialect and fails if a column name is wrong.

## Troubleshooting
* **"model unavailable" notice** – start Ollama / `ollama pull <your model>`; facts still show.
* **"Your session has expired"** – sign in again. **404 on /api/copilot/chat** – router not registered in `main.py`.
* **Button not floating** – older Streamlit; check `pip show streamlit`.
* **Clerk sees "document belongs to another user"** – see assumption 3.
