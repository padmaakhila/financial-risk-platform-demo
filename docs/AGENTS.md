# The four agents / services

Every component has a closed set of allowed tools. The workflow tool allowlist is `backend/agents/tools.py`; there is no tool for payments, approvals, arbitrary SQL, shell or code execution.

## A. Extraction Agent (`services/extraction.py`)
- **Responsibility**: read a document, measure confidence, produce schema-validated fields with evidence.
- **Input**: stored file path (validated upload).
- **Output**: `ExtractionResult` (status ok / needs_manual_entry / failed, document kind, fields with confidence, method, page, snippet, bounding box, DOC_* findings, validated data).
- **Allowed tools**: pdfplumber, Tesseract (via pytesseract), rule parsers, Pydantic validation, optional injected LLM mapper (output accepted only if the value appears verbatim in the text; never given database access).
- **Errors**: corrupt/hostile file -> `needs_manual_entry` or `failed` with a safe message (never a crash). Unreadable scan: one retry with an alternative OCR configuration, then manual entry. Tesseract missing -> manual entry with install hint.
- **Hand-off**: stored by `extraction_db.py`; the worker queues the invoice workflow.
- **Confidence**: text layer = 1.0 (`pdf_text`); OCR = mean word confidence (`ocr_word_conf`); LLM-supplied = no number (`llm_estimate`, flagged for verification).

## B. Matching Service (`services/matching.py`, deterministic, no LLM)
- **Responsibility**: arithmetic checks, two-way and three-way matching, duplicate detection, exception records with severity.
- **Input**: invoice, vendor master, PO, GRN, earlier invoices, tolerances (database `settings`).
- **Output**: findings (rule id, severity, expected, actual, difference, evidence) stored as `exceptions`; overall result pass / warning / fail.
- **Allowed tools**: SQLAlchemy read queries, Python rule engine, RapidFuzz.
- **Errors**: missing PO/GRN is an exception (not a crash). Database outage -> job retried, then FAILED.
- **Hand-off**: Risk Explanation Agent via stored findings.

## C. Risk Explanation Agent (`agents/risk_explainer.py`)
- **Responsibility**: explain stored findings in plain language with source references and caveats.
- **Input**: invoice header (no bank/tax IDs) and findings with redacted, delimiter-safe evidence.
- **Output**: JSON `{summary, items:[{finding_id, explanation}], caveats}`, then verified by code.
- **Allowed tools**: none (it receives evidence in the prompt and cannot call anything).
- **Verification** (`verify_explanation`): cited ids exist; every number appears in the cited finding; page citations exist in the evidence; all medium+ findings are explained; no approve/pay instruction. Max 2 retries, then deterministic template.
- **Errors**: timeout/outage -> template immediately (no retry loop). Malformed JSON counts as a failed attempt.
- **Hand-off**: stored explanation labelled `model` or `template`; case goes to the human review queue.

## D. Audit Summary Agent (`agents/audit_summarizer.py`)
- **Responsibility**: summarise the saved audit events and decision.
- **Input**: read-only audit events for the invoice.
- **Output**: short summary plus the original timeline (always shown, authoritative).
- **Verification**: numbers must occur in the events; "approved / rejected / paid / documents requested" must match recorded events.
- **Errors**: any LLM failure -> deterministic summary and raw timeline.
- **Hand-off**: reports and dashboards.
