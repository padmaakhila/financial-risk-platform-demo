# Architecture

Diagrams are Mermaid. They render on GitHub and in VS Code (install the extension "Markdown Preview Mermaid Support", then open the Markdown preview).

## 1. System architecture

```mermaid
flowchart LR
  subgraph Browser
    U[User]
  end
  subgraph UI["Streamlit UI (only frontend)"]
    P[9 pages + role-aware navigation]
  end
  subgraph API["FastAPI backend"]
    A[Auth: JWT + role check on every endpoint]
    R[Routers: documents, invoices, records, review, reports, admin, monitoring]
    S[Services: upload validation, extraction, matching, review, payments, reports]
  end
  subgraph WK["Worker process"]
    Q[(background_jobs table)]
    W[Worker: claim, retry, recover]
    G[Workflow: plan > tools > verify > review gate > audit]
  end
  DB[(SQLite default / SQL Server Express optional)]
  FS[(Uploads folder)]
  LLM[Ollama local or optional API]
  OCR[Tesseract / pdfplumber]
  ERP[Mock ERP :8101]
  VV[Mock vendor verification :8102]
  U --> P --> A --> R --> S --> DB
  S --> FS
  R -- enqueue --> Q
  W -- claim --> Q
  W --> G --> S
  G --> LLM
  G --> OCR
  G --> VV
  S -- only after recorded approval --> ERP
```

Rules of the design
- Streamlit only calls the API. No business rule lives in the UI.
- Deterministic Python code decides every financial fact. The LLM only explains stored findings, and its output is verified by code.
- Payments exist in exactly one code path (`services/payments.py`) and need a recorded human approval.
- Long work runs in the worker; the UI polls job status.

## 2. Agent / workflow graph

```mermaid
flowchart TD
  REQ[Request: process invoice] --> PLAN[Classification + planning]
  PLAN -->|already reviewed| STOP[Halt: never reprocess]
  PLAN --> VEND[Vendor verification tool]
  VEND --> MATCH[Matching Service: arithmetic, 2/3-way, duplicates, exceptions]
  MATCH --> EXPL[Risk Explanation Agent: LLM]
  EXPL --> VER{Verification}
  VER -->|numbers/citations OK| SAVE[Store explanation]
  VER -->|rejected, retries left max 2| EXPL
  VER -->|rejected, no retries left| FB[Template fallback]
  EXPL -->|timeout / outage| FB
  FB --> SAVE
  SAVE --> GATE[Review gate: status AWAITING_REVIEW]
  GATE --> AUD[Audit event]
  AUD --> HUMAN[Human decision in review queue]
  HUMAN -->|approve + explicit payment request| PAY[Mock ERP, idempotent]
```

## 3. Entity relationship diagram

```mermaid
erDiagram
  users ||--o{ reviews : makes
  users ||--o{ documents : uploads
  users ||--o{ audit_events : "acts in"
  vendors ||--o{ purchase_orders : receives
  vendors ||--o{ invoices : bills
  purchase_orders ||--|{ purchase_order_lines : has
  purchase_orders ||--o{ goods_receipts : "received by"
  goods_receipts ||--|{ goods_receipt_lines : has
  documents ||--o{ invoices : "source of"
  documents ||--o{ extracted_fields : yields
  invoices ||--|{ invoice_lines : has
  invoices ||--o{ extracted_fields : "evidence for"
  invoices ||--o{ exceptions : raises
  invoices ||--o{ reviews : "decided by"
  invoices ||--o{ ai_outputs : explained_by
  invoices ||--o{ workflow_checkpoints : tracked_by
  invoices ||--o{ background_jobs : processed_by
  invoices ||--o{ integration_records : calls
  invoices ||--o{ llm_usage : consumes
  invoices ||--o{ scenario_ground_truth : "expected outcome"
  users { int id PK  string username  string password_hash  string role  bool is_active }
  vendors { int id PK  string vendor_code  string name  string tax_id  string bank_account  string verification_status }
  purchase_orders { int id PK  string po_number  int vendor_id FK  date order_date  string currency }
  goods_receipts { int id PK  string grn_number  int po_id FK  date receipt_date }
  documents { int id PK  string stored_filename  string sha256  string doc_type  string status  int uploaded_by FK }
  invoices { int id PK  int seq  string invoice_number  int vendor_id FK  decimal grand_total  string status  int version }
  invoice_lines { int id PK  int invoice_id FK  int line_no  decimal quantity  decimal unit_price  decimal line_total }
  extracted_fields { int id PK  string field_name  float confidence  string confidence_method  int page_number  string source_snippet }
  exceptions { int id PK  int invoice_id FK  string rule_id  string severity  string expected_value  string actual_value  json source_evidence }
  reviews { int id PK  int invoice_id FK  int reviewer_id FK  string decision  string idempotency_key }
  audit_events { int id PK  string action  string entity_type  string entity_id  string prev_hash  string event_hash }
  background_jobs { string id PK  string job_type  string status  int attempts  datetime run_after }
  workflow_checkpoints { int id PK  int invoice_id FK  string node  json state }
  integration_records { int id PK  string integration  string idempotency_key  string status }
  ai_outputs { int id PK  string kind  string source  text summary }
  llm_usage { int id PK  string provider  int prompt_tokens  int completion_tokens  string outcome }
  settings { string key PK  string value }
  scenario_ground_truth { int id PK  string scenario_code  json expected }
```

## 4. Workflow sequence (happy path with approval and payment)

```mermaid
sequenceDiagram
  actor Clerk
  actor Reviewer
  participant UI as Streamlit
  participant API as FastAPI
  participant DB as Database
  participant W as Worker
  participant VV as Vendor mock
  participant LLM as Ollama/template
  participant ERP as ERP mock
  Clerk->>UI: upload invoice PDF
  UI->>API: POST /api/documents (JWT)
  API->>API: validate type, size, signature, name
  API->>DB: store document + enqueue job
  API-->>UI: 202 job_id
  W->>DB: claim job (atomic)
  W->>W: extract (text layer or OCR), validate schema
  W->>DB: invoice, fields (page, snippet, confidence), DOC_* findings
  W->>VV: verify tax id + bank (retry x2, timeout)
  W->>W: arithmetic, 3-way match, duplicates (Decimal, deterministic)
  W->>DB: exceptions
  W->>LLM: redacted findings only
  LLM-->>W: JSON explanation (or timeout)
  W->>W: verify numbers + citations (max 2 retries) else template
  W->>DB: explanation, status AWAITING_REVIEW, audit event
  Reviewer->>UI: open case, read evidence
  UI->>API: POST decision (approve, idempotency key)
  API->>DB: guarded status update + review + audit
  Reviewer->>UI: release payment
  UI->>API: POST payment
  API->>DB: check approval, reserve idempotency record
  API->>ERP: POST /payments (Idempotency-Key)
  ERP-->>API: 201 POSTED
  API->>DB: PAID + audit event
```

## 5. Which technique does what

| Step | Technique | Why |
|---|---|---|
| Login, roles, permissions | Deterministic code | Security must be predictable |
| Document type | scikit-learn TF-IDF classifier + keyword-rule fallback | Small, fast, explainable |
| Text from PDF / scans | pdfplumber, Tesseract (measured word confidence) | Standard tools |
| Field extraction | Rule parsers + Pydantic; optional LLM mapping accepted only if the value appears verbatim in the text | Layouts vary; schema and text check catch mistakes |
| Arithmetic, matching, tolerances | Python `Decimal`, rule engine | Money must be exact and repeatable |
| Duplicates | Exact key, then RapidFuzz weighted score | Finds near-duplicates |
| Exceptions and severity | Fixed severity table | Traceable to a rule |
| Risk explanation | LLM (or template) | Plain language only |
| Verification | Deterministic validators | Stops invented numbers and citations |
| Approval | Human | Consequential action |
| Audit log | Hash-chained append-only table | Tamper-evident (not immutable) |
| Audit summary | LLM (or template) over saved events | Readable; raw events stay authoritative |
| Dashboards, reports | SQL + Python aggregation | Numbers must match the database |
