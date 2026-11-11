"""Shared constants: roles, statuses, rule identifiers, formats and default settings."""
from decimal import Decimal

ROLES = ("admin", "reviewer", "ap_clerk", "auditor")

INVOICE_STATUSES = (
    "RECEIVED", "PROCESSING", "NEEDS_MANUAL_ENTRY", "AWAITING_REVIEW",
    "DOCUMENTS_REQUESTED", "APPROVED", "REJECTED", "PAYMENT_PENDING", "PAID", "FAILED",
)
SEVERITIES = ("info", "low", "medium", "high", "critical")
EXCEPTION_STATUSES = ("OPEN", "RESOLVED", "WAIVED")
JOB_STATUSES = ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "RETRYING", "CANCELLED")
REVIEW_DECISIONS = ("approve", "reject", "request_documents")
DOCUMENT_TYPES = ("invoice", "purchase_order", "goods_receipt", "vendor_record", "unknown")
DOCUMENT_KINDS = ("digital_pdf", "scanned_good", "scanned_low_quality", "scanned_unreadable", "unsupported")

# Fictional identifier formats used by the whole platform (synthetic data only).
TAX_ID_REGEX = r"^TX\d{9}$"
BANK_ACCOUNT_REGEX = r"^FB\d{2}[A-Z]{4}\d{10}$"

# Rule identifiers (the ground truth and the Matching Service use the same ids).
RULE_IDS = (
    "ARITH_LINE_TOTAL", "ARITH_TAX", "ARITH_SUBTOTAL", "ARITH_GRAND_TOTAL",
    "MATCH_PRICE", "MATCH_QTY_PO", "MATCH_QTY_GRN", "MATCH_MISSING_PO",
    "MATCH_MISSING_GRN", "MATCH_PARTIAL_GRN",
    "DUP_EXACT", "DUP_FUZZY",
    "VAL_TAX_ID", "VAL_BANK_FORMAT", "VAL_MISSING_FIELD",
    "DOC_UNREADABLE", "DOC_LOW_CONF", "DOC_UNSUPPORTED_TYPE", "SEC_PROMPT_INJECTION",
    # extra rules beyond the synthetic ground truth (never fire on clean data)
    "MATCH_VENDOR", "MATCH_ITEM", "MATCH_TAX_RATE", "VAL_BANK_MISMATCH", "VAL_VENDOR_REJECTED",
)

# Default tunable settings (stored in the `settings` table, editable by admins).
DEFAULT_SETTINGS = {
    "price_tolerance_pct": ("1.00", "Allowed invoice vs PO unit price difference (%)"),
    "qty_tolerance_pct": ("0.00", "Allowed quantity over PO/GRN (%)"),
    "amount_tolerance_abs": ("0.01", "Allowed absolute rounding difference per amount"),
    "duplicate_threshold": ("0.85", "Weighted similarity score at or above which an invoice is a suspected duplicate"),
    "low_confidence_threshold": ("0.70", "Field confidence below this is flagged"),
    "max_verification_retries": ("2", "Maximum explanation verification retries"),
    "llm_timeout_seconds": ("60", "Per-call LLM timeout"),
}
CURRENCY_QUANT = Decimal("0.01")
