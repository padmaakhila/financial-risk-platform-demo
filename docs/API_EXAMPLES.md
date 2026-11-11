# API request examples

Base URL `http://localhost:8000`. Interactive docs: `/docs`. Postman: `docs/postman_collection.json`. Money values are strings. All errors look like `{"error": {"code", "message", "request_id"}}`.

## Login
```bash
curl -s -X POST http://localhost:8000/api/auth/login -H "Content-Type: application/json" \
     -d '{"username":"reviewer","password":"<demo password>"}'
# -> {"access_token":"...","token_type":"bearer","expires_in":1800,"username":"reviewer","role":"reviewer"}
```
PowerShell: `$t = (Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/auth/login -ContentType application/json -Body '{"username":"reviewer","password":"..."}').access_token`

## Upload and follow the job
```bash
curl -s -X POST http://localhost:8000/api/documents -H "Authorization: Bearer $T" -F "file=@data/demo/demo_success_invoice.pdf;type=application/pdf"
# 202 {"document_id":12,"job_id":"3f2a...","status":"QUEUED"}
curl -s http://localhost:8000/api/jobs/3f2a... -H "Authorization: Bearer $T"
# {"job_id":"3f2a...","status":"SUCCEEDED","progress_pct":100,...}
```
Rejected upload: `415 {"error":{"code":"UNSUPPORTED_FILE_TYPE","message":"File type '.exe' is not supported. Allowed: ...","request_id":"..."}}`

## Review decision (idempotent)
```bash
curl -s -X POST http://localhost:8000/api/invoices/1/decision -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
     -d '{"decision":"approve","comment":"Checked against PO and GRN.","idempotency_key":"6c1f0d9e-0001"}'
# 200 {"review_id":5,"invoice_id":1,"decision":"approve","invoice_status":"APPROVED"}
```
Sending the same key again returns the same review. A different action on a decided invoice returns `409 INVALID_STATE`.

## Payment (only after approval)
```bash
curl -s -X POST http://localhost:8000/api/invoices/1/payment -H "Authorization: Bearer $T"
# 200 {"status":"PAID","payment_id":"PAY-000001","replayed":false}
# 202 {"status":"PAYMENT_PENDING","retry":true,"reason":"The ERP is unavailable; ..."}
# 409 {"error":{"code":"APPROVAL_REQUIRED",...}}   <- no recorded approval
```

## Reports and monitoring
`GET /api/reports/summary`, `GET /api/reports/reconciliation.csv`, `GET /api/reports/reconciliation.pdf`, `GET /api/monitoring/metrics`, `GET /api/audit/verify`.

## Mock ERP (port 8101)
```
POST /payments   headers: Idempotency-Key: <unique per payment>
body: {"invoice_number":"INV-000001","vendor_code":"V0001","amount":"123.45","currency":"USD","approval_id":"7"}
201 {"payment_id":"PAY-000001","status":"POSTED","replayed":false,...}   200 same key + same body (replayed:true)
400 missing key | 409 key reused with a different body, or a payment for this approval already exists | 422 invalid body | 503 simulated outage
POST /admin/simulate {"mode":"normal|down|timeout|flaky","fail_n":2}    POST /admin/reset
```

## Mock vendor verification (port 8102)
```
POST /verify  {"tax_id":"TX123456789","bank_account":"FB12ABCD1234567890"}
200 {"request_id":"VV-000001","status":"VERIFIED|REJECTED|NOT_FOUND|INVALID","tax_id_status":"VERIFIED|REJECTED|NOT_FOUND|INVALID_FORMAT",
     "bank_status":"MATCH|MISMATCH|NOT_PROVIDED","checked_at_utc":"..."}
422 missing tax_id | 503 simulated outage | timeout mode sleeps | flaky mode fails the first N calls
POST /admin/simulate {"mode":"normal|down|timeout|flaky|reject_all","fail_n":2}
```
The platform client retries retryable failures at most twice (3 attempts) with back-off, then reports the service as unavailable; it never marks anything successful after a failure.
