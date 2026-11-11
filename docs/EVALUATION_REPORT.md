# Evaluation report (template + how to produce real numbers)

Run on your machine (after installing requirements and starting nothing else):
```powershell
python -m scripts.run_evaluation --with-tests          # full mode: database + workflow + mock services, then pytest
python -m scripts.run_evaluation --provider ollama --limit 25 --timeout 60   # measure a real local model on 25 invoices
```
Output: `reports/evaluation_report.md` and `reports/evaluation_results.json`. Paste the headline table into your submission.

## What is measured
| Measure | Source |
|---|---|
| Exact match, rule precision/recall vs ground truth (24 scenarios, 520 invoices) | run on the synthetic dataset |
| Workflow latency p50 / p95 / max | wall time per invoice, nearest-rank percentiles |
| Error rate | invoices where the workflow raised an exception |
| Model vs template explanations and fallback reasons | stored `ai_outputs` / `llm_usage` |
| Tokens per task and cost | provider-reported usage only (local models report tokens, no cost) |
| Acceptance spot-checks | payment gate, idempotency, ERP outage, audit chain (full mode) |
| Test counts | `pytest -q` summary line |

## Result recorded during development (honest scope)
`reports/evaluation_report_pure_mode_sandbox.md` was produced in a build sandbox without a database stack, using **pure mode** (Matching Service + template explanations): 520/520 invoices matched the ground truth, 0 errors, p50 0.7 ms and p95 1.3 ms per invoice for matching plus explanation. The 5 LLM-timeout scenarios were simulated with a deliberately slow fake provider and all fell back to templates. **The full-mode run, the pytest run on the complete suite and any real-model run must be done on your machine**; I did not run them, so no such numbers are claimed here.

## Interpreting results
- Perfect scores on planted errors prove the rules implement the design, not real-world accuracy.
- Real OCR quality is only tested on clean synthetic scans and a noise-damaged one.
- Latency with an 8 GB CPU-only laptop will be dominated by the model; the 30 s default timeout may trigger fallbacks, which is correct behaviour.
- Risks and mitigations are listed in `docs/BRD.md` section 7 and `docs/SECURITY.md`.
