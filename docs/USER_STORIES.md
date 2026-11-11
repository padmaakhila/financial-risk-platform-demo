# User stories and acceptance matrix

| ID | Story | Acceptance criteria | Verified by |
|---|---|---|---|
| US-01 | As a clerk I upload an invoice so it is processed without waiting | Upload returns 202 with a job id; page shows progress; worker does the work; bad files give a clear error | `test_api.py::test_valid_upload...`, `test_upload_validation.py`, `test_ui_pages.py` |
| US-02 | As a clerk I see what was extracted and how sure the system is | Fields show value, page, source text, confidence and method; low confidence is flagged | `test_extraction.py`, `test_ui_support.py` |
| US-03 | As a reviewer I want arithmetic and tax recalculated exactly | Decimal recalculation; each mismatch is an exception with expected/actual/difference | `test_matching.py` |
| US-04 | As a reviewer I want invoices matched to POs and GRNs | Price, quantity, missing PO/GRN, partial receipt detected within tolerances | `test_matching.py`, `test_workflow_db.py` |
| US-05 | As a reviewer I want suspected duplicates flagged | Exact and fuzzy duplicates flagged on the later invoice; score and signals stored; no false positives | `test_matching.py`, evaluation report |
| US-06 | As a reviewer I want plain-language explanations tied to evidence | Explanation cites finding ids; numbers verified; source page/snippet shown; labelled AI or template | `test_agents.py`, `test_ui_pages.py` |
| US-07 | As a reviewer I want a safe fallback when the AI is slow or wrong | Timeout/outage/bad output -> template within bounds; case still reaches review | `test_agents.py`, `test_workflow.py` |
| US-08 | As a reviewer I approve, reject or request documents with a recorded reason | Decision stored with actor/time; duplicate click is idempotent; wrong state rejected | `test_review_payments.py`, `test_api.py` |
| US-09 | As finance I want no payment without approval | API returns 409 APPROVAL_REQUIRED; ERP never called | `test_review_payments.py`, `test_api.py` |
| US-10 | As finance I want retries not to double-pay | Same key returns same payment; one ERP record | `test_review_payments.py`, `test_integrations.py` |
| US-11 | As finance I want ERP outages not to corrupt data | Invoice stays PAYMENT_PENDING; recovery pays once | `test_review_payments.py`, `test_api.py` |
| US-12 | As an unauthorized user I cannot read or change restricted data | 401 without token; 403 wrong role; denials audited | `test_api.py` |
| US-13 | As an auditor I want an audit trail I can trust | Hash chain verifies; tampering detected; summary never replaces raw events | `test_database.py`, `test_agents.py`, `test_api.py` |
| US-14 | As a manager I want dashboards and downloadable reports that agree with the data | Totals equal database; CSV and PDF export; export audited | `test_support_modules.py`, `test_api.py` |
| US-15 | As an admin I manage users, tolerances and test outages | Validation, last-admin protection, audited changes | `test_api.py`, `test_ui_pages.py` |
| US-16 | As an operator I want failures visible | Monitoring shows failed jobs, p50/p95, error rate, AI usage, integration health | `test_support_modules.py`, `test_api.py` |
| US-17 | As a student I can reset and reproduce the dataset | Seeded generator; reset script with backup | `test_data_generator.py`, `test_database.py` |

## Critical gates (must pass regardless of anything else)
1. Unauthorized access is denied (US-12). 2. No payment without recorded approval (US-09). 3. No duplicate payment on retry (US-10). 4. Outage does not corrupt records (US-11). 5. LLM cannot change calculated values (`test_workflow.py::test_workflow_cannot_change_calculated_findings`).
