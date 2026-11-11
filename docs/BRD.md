# Business Requirements Document (BRD)

**Project**: Financial Document & Risk Analysis Platform (Capstone 04). **Data**: synthetic only.

## 1. Business problem
Accounts-payable (AP) teams must reconcile invoices against purchase orders (PO) and goods-received notes (GRN) before paying. Manual checking is slow and error-prone; duplicate invoices, wrong totals, wrong tax, price or quantity differences and missing receipts lead to overpayment and fraud risk. Reviewers also need to understand *why* a case was flagged and prove who decided what.

## 2. Objectives
1. Process invoices accurately and quickly: extract, recalculate, match, detect duplicates.
2. Make every discrepancy traceable to the original document evidence.
3. Keep money decisions deterministic and human-approved; use AI only to explain.
4. Keep a complete, tamper-evident audit trail.
5. Run for free on a beginner's laptop (SQLite, optional local model), with a documented, cost-checked AWS path.

## 3. Stakeholders and users
| Role | Needs |
|---|---|
| AP clerk | Upload documents, see extraction status, view records |
| Finance reviewer | Understand findings, approve / reject / request documents, release payments |
| Auditor | Read-only evidence, audit trail, reports |
| Administrator | Users, roles, matching tolerances, integration health |
| Student/assessor | Evidence that critical authorization, approval and integrity tests pass |

## 4. Scope
**In scope**: upload (invoice, PO, GRN, vendor CSV); classification; extraction with confidence and evidence; arithmetic and tax checks; 2-/3-way matching; duplicate detection; exception records; AI/template explanations with verification; review queue; mock ERP payment; vendor verification mock; audit trail and summary; dashboards; CSV/PDF reports; monitoring; admin; synthetic data (520 invoices, 24 scenarios); tests; Windows and AWS guides.

**Out of scope**: real banking/ERP, real tax authority checks, multi-currency conversion, cumulative over-billing across several invoices on one PO, e-invoicing standards, production-grade identity provider.

## 5. Business rules
1. The LLM never calculates, creates findings, changes values, approves or pays.
2. A payment requires a recorded human approval and is idempotent.
3. A fuzzy duplicate is a suspicion for review, not proof of fraud.
4. Differences inside configured tolerances pass; outside they fail or warn.
5. Unreadable documents go to manual entry; a timed-out workflow never approves or pays anything.
6. Approving with open high/critical findings needs a written justification; uploaders cannot approve their own uploads (non-admin).

## 6. Success measures
- All seeded duplicates and calculation errors detected; no false positives on clean invoices (evaluation report).
- Critical authorization, approval and integrity tests pass (acceptance matrix).
- p50/p95 workflow latency, error rate and AI usage reported from a defined test set.
- A beginner can install and run everything from the README on Windows.

## 7. Assumptions, risks, mitigations
| Risk | Mitigation |
|---|---|
| Small local LLM gives poor or slow answers | Deterministic verification + template fallback; timeouts |
| OCR errors on poor scans | Measured confidence, low-confidence flags, manual entry path |
| AWS surprise charges | Cost-checked guide, budgets, cleanup checklist; no paid services without approval |
| SQLite concurrency | One worker, WAL mode, documented limit; SQL Server Express option |
| Prompt injection in documents | Data-not-instructions handling, no LLM tools, verification |
