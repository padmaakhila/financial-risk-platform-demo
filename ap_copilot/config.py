"""Static limits for the Copilot. Deployment settings (Ollama URL, model,
timeouts, DB URL, secrets) are NOT defined here; they come from the existing
``request.app.state.settings`` object."""
from decimal import Decimal

MODEL_LABEL = "Qwen 2.5"          # display only; the real model is chosen by the existing provider
MAX_QUESTION_CHARS = 1000
MAX_ANSWER_CHARS = 3500            # cap for the LLM-written part
MAX_CONTEXT_CHARS = 6000           # cap for the text handed to the LLM
COPILOT_MAX_LLM_SECONDS = 15     # keeps total request under the UI ApiClient 30 s default timeout

MAX_IDENTIFIERS = 8
MAX_INVOICES = 5
MAX_DETAIL_INVOICES = 2            # invoices that get exceptions/fields/history attached
MAX_VENDORS = 5
MAX_POS = 4
MAX_GRNS = 4
MAX_LINES = 10
MAX_FIELDS = 40
MAX_EXCEPTIONS = 20
MAX_REVIEWS = 5
MAX_CHECKPOINTS = 10
MAX_AUDIT = 10
MAX_LIST = 10                      # rows for "pending" / "high risk" listings

MAX_SNIPPET_CHARS = 160
MAX_NOTE_CHARS = 200
MAX_FIELD_VALUE_CHARS = 120
MAX_TEXT_CHARS = 200

LOW_CONFIDENCE = Decimal("0.70")

# Header fields that, when empty on the stored invoice, are reported as "not recorded".
HEADER_FIELDS = (
    "invoice_number", "invoice_date", "due_date", "po_number", "grn_number",
    "vendor_tax_id_raw", "subtotal", "tax_total", "grand_total", "currency",
)
