# Demonstration script (12-14 minutes)

**Preparation (before recording):** `python -m scripts.reset_database --yes`, `python -m scripts.make_demo_documents`, start the five processes (see README), open http://localhost:8501. Have a reviewer, a clerk and an auditor login ready (printed by the seed script). Optional: Ollama running. Keep `data\demo` open in a file window.

| Time | Scene | What to do / say |
|---|---|---|
| 0:00-1:00 | Intro | "A finance portal, not a chatbot. Deterministic code decides every number; AI only explains; a human approves; everything is audited." Show the architecture diagram (docs/ARCHITECTURE.md). |
| 1:00-2:30 | Login and roles | Sign in as **clerk**: note the sidebar has no Review or Admin pages. Open Review page URL manually? Not listed. Sign out, sign in as **reviewer**. Mention the API enforces roles even if the UI is bypassed. |
| 2:30-3:30 | Invalid input | As clerk upload `demo_invalid.exe` (clear "not supported" message) then `demo_fake.pdf` ("does not look like a real PDF"). Nothing is stored. |

## Success path: clean invoice (about 3 minutes)
| Time | Step | Expected result |
|---|---|---|
| 3:30 | **Upload** `demo_success_invoice.pdf` (clerk) | Preview of page 1; "Upload and process"; progress bar; the page stays responsive because the worker does the work |
| 4:15 | **Extract** | Fields table: every value with page, source text and confidence "100% (text layer)" |
| 4:45 | **Check** (AI / Agent Workflow page) | Stages all done; arithmetic and 3-way match show "no findings"; no duplicate |
| 5:15 | **Explain** | "No discrepancies"; label says AI-generated (verified) if Ollama ran, otherwise Template-generated |
| 5:45 | **Approve** (sign in as reviewer; Review & Approval) | Case in queue; read the evidence tabs; tick the confirmation; Approve; status Approved |
| 6:30 | **Post + audit** | "Release payment" with confirmation: PAID with an ERP reference. History tab shows each event with actor and time. Monitoring > Verify audit chain: intact |

## Failure / approval path: duplicate and wrong tax (about 4 minutes)
| Time | Step | Expected result |
|---|---|---|
| 7:00 | **Upload** `demo_failure_invoice.pdf` | Processing completes |
| 7:30 | **Detect** | Findings: `DUP_EXACT` (same vendor and invoice number as an earlier invoice) and `ARITH_TAX` (stated tax differs from the recalculation). Severities from a fixed table |
| 8:15 | **LLM timeout** | Stop Ollama (or set `LLM_TIMEOUT_SECONDS=1`), re-process: the explanation is **Template-generated**, the banner says why (timeout/unavailable); findings are identical. Show Monitoring: fallback count and reason |
| 9:00 | **Trace** | Open an exception's Evidence expander: stored evidence plus the original source snippet and page; original document preview |
| 9:45 | **Decide** | Reviewer: Request documents or Reject with a comment (reject without a comment is refused) |
| 10:15 | **No payment without approval** | Open http://localhost:8000/docs, Authorize as reviewer, `POST /api/invoices/{id}/payment` for that invoice: **409 APPROVAL_REQUIRED**. Audit trail shows PAYMENT_BLOCKED. ERP was never called |

## Resilience extras (about 3 minutes, pick any)
| Scenario | How | What to point out |
|---|---|---|
| ERP outage | Administration > Integrations > ERP mode `down`; approve a second invoice and release payment | "Payment pending", never PAID; set mode `normal`, press again: PAID once; pressing again is a safe replay |
| Vendor service outage | Vendor mode `down`, process an invoice | Case still reaches review with the caveat "vendor verification unavailable" |
| Unauthorized | Auditor tries Review page (not listed); in `/docs` an auditor token on `POST .../decision` | 403 and an ACCESS_DENIED audit event |
| Prompt injection | Search records for invoices with notes "Ignore all previous instructions..." | Flagged `SEC_PROMPT_INJECTION`; text treated as data, removed from prompts |
| Scans | Upload `demo_scanned_invoice.pdf` (needs Tesseract), then `demo_unreadable_scan.pdf` | OCR confidence shown; unreadable goes to manual entry with a visible finding |

## Closing (13:00-14:00)
Show `reports/evaluation_report*.md`: accuracy against ground truth, p50/p95 latency, error rate, AI usage. State the limits honestly (synthetic data, mock integrations, tamper-evident audit not immutable). Show the traceability matrix.

**Presenter tips:** keep one terminal visible with worker logs (shows retries and fallbacks); if the model is slow, say so and let the fallback happen, that *is* the demo of safe behaviour.
