# Security controls and limitations

| Area | Control | Where |
|---|---|---|
| Authentication | scrypt password hashes (stdlib), short-lived JWT (default 30 min), generic login errors, lockout after 5 failures / 5 min, logout revokes the token | `core/security.py`, `auth/throttle.py`, `api/routes_core.py` |
| Authorization | One permission table; roles read from the database on every request; checked on every endpoint; denials are audited | `auth/permissions.py`, `api/deps.py` |
| Approval | Payment needs a recorded `approve` review; status machine blocks skipping states; guarded UPDATE with version check | `services/review.py`, `services/payments.py`, `services/state_machine.py` |
| Idempotency | Unique review key; payment key `pay-<invoice>-<review>`; ERP also rejects key reuse and duplicate approvals | `reviews`, `integration_records`, `erp_mock_core.py` |
| Uploads | Extension allow-list, MIME vs extension, file signature, PDF end marker, size limit, safe server-generated names, no overwrite, path-traversal-safe lookup, duplicate-content detection | `services/upload_validation.py` |
| Evidence access | Clerks can only open documents they uploaded; bank details masked except admin/reviewer | `api/routes_core.py`, `api/views.py` |
| Prompt injection | Document text is data: instruction-like phrases are detected (flagged) and removed from prompts; delimiters stripped; LLM has no tools; output verified by code | `services/validation.py`, `services/redaction.py`, `agents/risk_explainer.py` |
| PII | Bank accounts, tax IDs, emails, phones redacted before prompts; logs scrub secrets and PII | `services/redaction.py`, `core/logging_setup.py` |
| LLM safety | External API OFF unless `LLM_API_ENABLED=true` plus URL/key/model; never silently chosen; timeouts and template fallback | `agents/llm.py` |
| Errors | One envelope with request id; no stack traces or echoed input | `api/errors.py` |
| Reports | CSV formula-injection guard; every export audited | `services/reports.py` |
| Secrets | Environment variables only; production refuses the default `SECRET_KEY` | `core/config.py` |
| Audit | Append-only table with SHA-256 hash chain | `services/audit.py` |

## Known limitations (be honest about these in the demo)
- The audit hash chain is **tamper-evident, not immutable**: someone with database access can rewrite rows and recompute the chain. Use database permissions and off-box backups for stronger guarantees.
- Login throttling and token revocation are in API process memory (lost on restart; not shared between instances).
- Prompt-injection detection is pattern based and can be evaded; the real defences are "no tools for the LLM" and deterministic verification.
- SQLite allows one writer at a time; run one worker. HTTPS is not terminated by the app (see the AWS guide for a reverse proxy).
- The mock ERP and vendor services are simulations; real integrations need real authentication and contracts.
- No malware scanning of uploaded files; files are never executed, only parsed by pdfplumber / Pillow / Tesseract.
