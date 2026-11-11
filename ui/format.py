
"""Pure presentation helpers (no Streamlit import, so they are unit-tested)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from ui.api_client import ApiProblem, Unauthorized, Unreachable


# ---------------------------------------------------------
# DISPLAY LABELS
# ---------------------------------------------------------

SEVERITY = {
    "critical": "🔴 Critical",
    "high": "🟠 High",
    "medium": "🟡 Medium",
    "low": "🟢 Low",
    "info": "ℹ️ Info",
}

STATUS = {
    "RECEIVED": "📥 Received",
    "PROCESSING": "⏳ Processing",
    "NEEDS_MANUAL_ENTRY": "✏️ Needs manual entry",
    "AWAITING_REVIEW": "🕒 Awaiting review",
    "DOCUMENTS_REQUESTED": "📄 Documents requested",
    "APPROVED": "✅ Approved",
    "REJECTED": "❌ Rejected",
    "PAYMENT_PENDING": "⏱️ Payment pending",
    "PAID": "💰 Paid",
    "FAILED": "⚠️ Failed",
}

GROUPS = {
    "ARITH": "Arithmetic",
    "MATCH": "PO / GRN matching",
    "DUP": "Duplicates",
    "VAL": "Field validation",
    "SEC": "Security",
    "DOC": "Document quality",
}

SEVERITY_ORDER = [
    "critical",
    "high",
    "medium",
    "low",
    "info",
]


# ---------------------------------------------------------
# STATUS AND SEVERITY
# ---------------------------------------------------------

def severity_label(s: str | None) -> str:
    """Return a readable severity label."""

    if not s:
        return "—"

    return SEVERITY.get(s, s.replace("_", " ").title())


def status_label(s: str | None) -> str:
    """Return a readable invoice status."""

    if not s:
        return "—"

    return STATUS.get(s, s.replace("_", " ").title())


# ---------------------------------------------------------
# CURRENCY FORMATTING
# ---------------------------------------------------------

def money(value, currency: str | None = None) -> str:
    """Format a financial value without changing its underlying value."""

    if value in (None, ""):
        return "—"

    try:
        formatted = f"{Decimal(str(value)):,.2f}"
    except (InvalidOperation, ValueError, TypeError):
        return str(value)

    return (
        f"{currency} {formatted}"
        if currency
        else formatted
    )


# ---------------------------------------------------------
# CONFIDENCE FORMATTING
# ---------------------------------------------------------

def confidence_label(
    conf,
    method: str | None,
) -> str:
    """Describe extraction confidence and its source."""

    if method == "none" or (
        conf is None and method is None
    ):
        return "Missing"

    if conf is None:
        if method == "llm_estimate":
            return "Not measured (AI-assisted; verify)"

        return "Not measured"

    source = {
        "pdf_text": "Text layer",
        "ocr_word_conf": "OCR",
    }.get(method or "", method or "")

    return f"{conf:.0%} ({source})"


def confidence_level(
    conf,
    threshold: float = 0.70,
) -> str:
    """Classify confidence against the supplied threshold."""

    if conf is None:
        return "unknown"

    return "ok" if conf >= threshold else "low"


# ---------------------------------------------------------
# EXCEPTION GROUPING
# ---------------------------------------------------------

def group_of(rule_id: str) -> str:
    """Identify the category from an exception rule ID."""

    prefix = rule_id.split("_", 1)[0]

    return GROUPS.get(prefix, "Other")


def group_exceptions(
    exceptions: list[dict],
) -> dict[str, list[dict]]:
    """Group exceptions and sort them by severity."""

    output: dict[str, list[dict]] = {}

    def severity_rank(exception):
        severity = exception.get("severity")

        try:
            return SEVERITY_ORDER.index(severity)
        except ValueError:
            return len(SEVERITY_ORDER)

    for exception in sorted(
        exceptions,
        key=severity_rank,
    ):
        group = group_of(
            exception.get("rule_id", "")
        )

        output.setdefault(group, []).append(exception)

    return output


# ---------------------------------------------------------
# SOURCE EVIDENCE
# ---------------------------------------------------------

def find_source_snippets(
    exception: dict,
    fields: list[dict],
) -> list[dict]:
    """Link a finding to its extracted-field evidence."""

    evidence = exception.get("evidence") or {}

    wanted = set()

    if evidence.get("field"):
        wanted.add(evidence["field"])

    if evidence.get("line_no") is not None:
        wanted.add(
            f"line_{evidence['line_no']}"
        )

    return [
        field
        for field in fields
        if field.get("name") in wanted
        and (
            field.get("snippet")
            or field.get("page")
        )
    ]


# ---------------------------------------------------------
# AI EXPLANATION BANNER
# ---------------------------------------------------------

def explanation_banner(
    source: str | None,
) -> tuple[str, str]:
    """Return the Streamlit message type and explanation."""

    if source == "model":
        return (
            "success",
            "AI-generated explanation. Every number and citation "
            "was verified against the stored findings.",
        )

    if source == "template":
        return (
            "warning",
            "Template-generated explanation. AI was unavailable, "
            "timed out, or its answer failed verification. "
            "The recorded findings below remain unchanged.",
        )

    return (
        "info",
        "No explanation has been generated yet.",
    )


# ---------------------------------------------------------
# API ERROR DISPLAY
# ---------------------------------------------------------

def friendly_error(e: ApiProblem) -> str:
    """Convert API errors into understandable frontend messages."""

    reference = (
        f" (reference {e.request_id})"
        if e.request_id
        else ""
    )

    if isinstance(e, Unreachable):
        return e.message

    if isinstance(e, Unauthorized):
        return (
            "Your session has ended. "
            "Please sign in again."
        )

    messages = {
        "FORBIDDEN": (
            "Your role is not allowed to do this."
        ),
        "APPROVAL_REQUIRED": (
            "A recorded human approval is required "
            "before a payment can be posted."
        ),
        "INVALID_STATE": e.message,
        "CONFLICT": e.message,
        "VALIDATION_FAILED": e.message,
        "TOO_MANY_ATTEMPTS": e.message,
        "INVALID_CREDENTIALS": (
            "Incorrect username or password."
        ),
        "INTERNAL_ERROR": (
            "The server had a problem. Please try again "
            f"or report it{reference}."
        ),
        "INTEGRATION_UNAVAILABLE": (
            "An external service is unavailable right now. "
            "The case is safe; try again later."
        ),
    }

    if e.code == "INVALID_REQUEST" and e.details:
        problems = [
            f"{item.get('field')} ({item.get('problem')})"
            for item in e.details[:4]
        ]

        return "Please check: " + "; ".join(problems)

    file_errors = {
        "UNSUPPORTED_FILE_TYPE",
        "SIGNATURE_MISMATCH",
        "MIME_MISMATCH",
        "FILE_TOO_LARGE",
        "EMPTY_FILE",
        "MALFORMED_FILE",
        "INVALID_FILENAME",
    }

    if e.code in file_errors:
        return f"File not accepted: {e.message}"

    return messages.get(
        e.code,
        f"{e.message}{reference}",
    )


# ---------------------------------------------------------
# GENERAL DATA HELPERS
# ---------------------------------------------------------

def rows(
    items: list[dict],
    columns: list[str],
) -> list[dict]:
    """Select specific columns from a list of dictionaries."""

    return [
        {
            column: item.get(column)
            for column in columns
        }
        for item in items
    ]


def human_seconds(x) -> str:
    """Format elapsed time for display."""

    if x is None:
        return "—"

    return (
        f"{x * 1000:.0f} ms"
        if x < 1
        else f"{x:.1f} s"
    )


def percent(x) -> str:
    """Format a decimal ratio as a percentage."""

    return (
        "—"
        if x is None
        else f"{x * 100:.1f}%"
    )