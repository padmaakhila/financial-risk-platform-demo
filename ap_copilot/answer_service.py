"""Turns retrieved context into safe, grounded or general AI answers.

Financial answers always include deterministic, data-derived facts when
records are available. Model explanations are appended only after strict
evidence-grounded validation.

General questions use the local language model without requiring database
retrieval. General answers use separate safety validation.

The assistant is read-only and never performs financial record actions.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from . import config
from .guardrails import validate_general_output, validate_output
from .prompts import (
    GENERAL_SYSTEM_PROMPT,
    HOWTO_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_general_user_prompt,
    build_user_prompt,
    help_text,
)
from .retrieval import has_data
from .security import Scope

log = logging.getLogger("ap_copilot")


# --------------------------------------------------------------- notices

NOTICE_UNAVAILABLE = (
    "_The local language model is unavailable (Ollama may be stopped "
    "or the model not installed), so only the recorded facts are shown._"
)

NOTICE_TIMEOUT = (
    "_The language model timed out, so only the recorded facts are shown._"
)

NOTICE_EMPTY = (
    "_The language model returned no explanation, "
    "so only the recorded facts are shown._"
)

NOTICE_INVALID = (
    "_The model's explanation failed safety validation and was discarded; "
    "only the recorded facts are shown._"
)

GENERAL_NOTICE_UNAVAILABLE = (
    "I couldn't connect to the local AI model. Please check that Ollama "
    "is running and that the configured model is available, then try again."
)

GENERAL_NOTICE_TIMEOUT = (
    "The local AI model took too long to respond. Please try again."
)

GENERAL_NOTICE_EMPTY = (
    "The local AI model returned an empty response. Please try again."
)

GENERAL_NOTICE_INVALID = (
    "The response did not pass safety validation, so I haven't displayed it. "
    "Please try rephrasing your question."
)


# ---------------------------------------------------------- conversation

GREETING_PATTERN = re.compile(
    r"(?:hi|hello|hey|good morning|good afternoon|good evening|how are you)"
    r"[!.?, ]*",
    re.IGNORECASE,
)

IDENTITY_PATTERN = re.compile(
    r"(?:who are you|what are you|what is this copilot|"
    r"what is this assistant|introduce yourself)"
    r"[!.?, ]*",
    re.IGNORECASE,
)

CAPABILITIES_PATTERN = re.compile(
    r"(?:what can you do|what can you do for me|what do you do|"
    r"what you can do|what are your capabilities|your capabilities|"
    r"how can you help|how can you assist me|"
    r"what can you help me with|what are your features|"
    r"list your features|what are you capable of)"
    r"[!.?, ]*",
    re.IGNORECASE,
)

WORKFLOW_PATTERN = re.compile(
    r"\b(?:invoice processing|invoice workflow|"
    r"invoice process|ap workflow|accounts payable workflow)\b",
    re.IGNORECASE,
)


def _simple_response(question: str) -> Optional[str]:
    """Return deterministic responses for common questions."""

    q = question.strip()

    if GREETING_PATTERN.fullmatch(q):
        return (
            "Hello! I'm your Financial Risk Copilot. "
            "I can explain the platform, help with general questions, "
            "and investigate financial records using authorized data. "
            "What would you like to explore?"
        )

    if IDENTITY_PATTERN.fullmatch(q):
        return (
            "I'm your Financial Risk Copilot, powered by the Qwen 2.5 "
            "language model through Ollama. I help users understand the "
            "financial risk platform and its records. I can explain "
            "invoices, exceptions, vendors, purchase orders, goods receipts "
            "and audit history using authorized platform data. "
            "I am read-only and cannot approve, reject, pay or modify records."
        )

    if CAPABILITIES_PATTERN.fullmatch(q):
        return (
            "**Here is what I can help you with:**\n\n"
            "1. **Invoice investigations:** Look up invoices using an "
            "invoice number and explain recorded findings.\n\n"
            "2. **PO and GRN checks:** Explain available purchase order "
            "and goods receipt matching information.\n\n"
            "3. **Risk findings:** Explain recorded exceptions, severity, "
            "expected values and actual values.\n\n"
            "4. **Data extraction:** Explain extracted invoice fields, "
            "missing information and low-confidence values.\n\n"
            "5. **Workflow guidance:** Explain invoice processing and "
            "the available platform sections.\n\n"
            "6. **Audit information:** Explain recorded review activity "
            "and audit history when authorized data is available.\n\n"
            "7. **General assistance:** Help with learning, programming, "
            "technical concepts and general questions.\n\n"
            "**Important:** Financial investigations use authorized "
            "platform data. I am read-only and cannot approve, reject, "
            "pay or modify financial records."
        )

    if WORKFLOW_PATTERN.search(q):
        return (
            "**Invoice Processing — Step by Step**\n\n"
            "At a high level, the accounts payable workflow works as follows:\n\n"
            "**1. Invoice Upload**\n"
            "An invoice document is submitted to the platform for processing.\n\n"
            "**2. Data Extraction**\n"
            "The system extracts available invoice information, such as "
            "invoice number, vendor details, dates, totals and line items.\n\n"
            "**3. Data Validation**\n"
            "Extracted information is checked for required fields and "
            "financial calculation issues.\n\n"
            "**4. Duplicate Detection**\n"
            "The platform checks for potential duplicate invoices.\n\n"
            "**5. PO and GRN Matching**\n"
            "Invoice information is compared with available purchase order "
            "(PO) and goods receipt note (GRN) records.\n\n"
            "**6. Risk Analysis**\n"
            "The risk engine identifies recorded issues such as amount "
            "mismatches, missing information and other exceptions.\n\n"
            "**7. Human Review**\n"
            "Authorized finance reviewers can examine flagged invoices "
            "and their supporting information.\n\n"
            "**8. Audit and Reporting**\n"
            "Recorded workflow activity, findings and review information "
            "can be examined through the platform.\n\n"
            "**Role of Copilot:** I explain available platform information. "
            "I do not make approval or payment decisions."
        )

    return None


# --------------------------------------------------------------- LLM

def _text_of(resp: Any) -> Optional[str]:
    if isinstance(resp, str):
        return resp

    for attr in ("text", "content", "output", "response"):
        value = getattr(resp, attr, None)

        if isinstance(value, str):
            return value

    return None


def default_llm_call(
    provider,
    system: str,
    user: str,
    timeout: float,
) -> Optional[str]:
    """Call the existing configured provider with deadline handling."""

    from backend.agents.llm import call_with_deadline

    response = call_with_deadline(
        provider,
        system,
        user,
        timeout,
    )

    return _text_of(response)


def _classify_llm_error(exc: BaseException) -> str:
    try:
        from backend.agents.llm import LLMTimeout, LLMUnavailable

        if isinstance(exc, LLMTimeout):
            return "model_timeout"

        if isinstance(exc, LLMUnavailable):
            return "model_unavailable"

    except Exception:
        pass

    return "model_error"


# ------------------------------------------------------------ rendering

def _v(value: Any) -> str:
    return "not recorded" if value in (None, "") else str(value)


def render_context_text(ctx: Dict[str, Any]) -> str:
    """Create compact JSON containing only retrieved context."""

    view = {
        key: ctx.get(key)
        for key in (
            "invoices",
            "vendors",
            "pos",
            "grns",
            "listing",
            "high_risk",
            "report",
            "not_found",
            "notes",
        )
        if ctx.get(key)
    }

    return json.dumps(
        view,
        default=str,
        ensure_ascii=False,
    )[:config.MAX_CONTEXT_CHARS]


def _verify_steps(
    inv: Dict[str, Any],
    vendors: List[Dict[str, Any]],
) -> List[str]:

    match = inv.get("match", {})
    steps = []

    if (
        match.get("po_reference_stored_on_invoice")
        and match.get("po_master_record_found") is False
    ):
        steps.extend([
            "Compare the PO number on the original invoice with the "
            "stored reference (%s)." %
            match["po_reference_stored_on_invoice"],

            "Check whether that PO exists in the purchase order master "
            "and belongs to this vendor.",
        ])

    elif not match.get("po_reference_stored_on_invoice"):
        steps.append(
            "No PO reference is stored on the invoice; "
            "check the original document for a PO number."
        )

    if (
        match.get("po_master_record_found")
        and match.get("po_vendor_same_as_invoice_vendor") is False
    ):
        steps.append(
            "The PO master record belongs to a different vendor "
            "than the invoice; confirm the correct vendor."
        )

    if (
        match.get("po_master_record_found")
        and match.get("po_currency_same_as_invoice") is False
    ):
        steps.append(
            "PO and invoice currencies differ; confirm which is correct."
        )

    if (
        match.get("grn_reference_stored_on_invoice")
        and match.get("grn_master_record_found") is False
    ):
        steps.append(
            "The GRN reference on the invoice has no goods receipt "
            "record; confirm receipt of goods with the warehouse."
        )

    if (
        match.get("grn_master_record_found")
        and match.get("grn_belongs_to_found_po") is False
    ):
        steps.append(
            "The GRN is linked to a different PO than the one on "
            "the invoice; verify the linkage."
        )

    if inv.get("exceptions"):
        steps.append(
            "Compare each finding's expected and actual values "
            "with the original invoice and the master records."
        )

    low = [
        field["field_name"]
        for field in inv.get("fields", [])
        if field.get("low_confidence")
    ]

    missing = [
        field["field_name"]
        for field in inv.get("fields", [])
        if field.get("missing")
    ]

    missing += list(inv.get("missing_header_fields", []))

    if low:
        steps.append(
            "Verify low-confidence extracted fields against "
            "the original document: %s." %
            ", ".join(low[:8])
        )

    if missing:
        steps.append(
            "Fill/verify missing values manually from the original "
            "document: %s." %
            ", ".join(dict.fromkeys(missing))
        )

    for vendor in vendors:
        status = str(
            vendor.get("verification_status", "")
        ).lower()

        if status not in ("verified", "approved"):
            steps.append(
                "Vendor %s has verification status '%s'; "
                "confirm vendor details independently." %
                (
                    vendor.get("vendor_code"),
                    _v(vendor.get("verification_status")),
                )
            )

    steps.append(
        "The absence of findings is not proof that an invoice is "
        "correct; verify against source documents before any decision."
    )

    return steps[:10]


def render_facts(
    ctx: Dict[str, Any],
    scope: Scope,
) -> str:

    out: List[str] = []

    for inv in ctx["invoices"]:

        out.append(
            "**Invoice:** %s — platform status: **%s**" %
            (
                _v(inv.get("invoice_number")),
                _v(inv.get("status")),
            )
        )

        out.append(
            "- Vendor on invoice: %s | Total: %s %s | Date: %s" %
            (
                _v(inv.get("vendor_name_raw")),
                _v(inv.get("grand_total")),
                _v(inv.get("currency")),
                _v(inv.get("invoice_date")),
            )
        )

        if "exceptions" not in inv:
            out.append(
                "_(Detail limited to the first %d matching invoices.)_" %
                config.MAX_DETAIL_INVOICES
            )
            continue

        out.append(
            "**Risk findings (platform risk engine):** " +
            (
                ""
                if inv["exceptions"]
                else "none retrieved. This does not prove "
                     "the invoice is correct."
            )
        )

        for exception in inv["exceptions"]:
            out.append(
                "- %s: severity %s, rule %s, status %s — "
                "expected %s, actual %s, difference %s `%s`" %
                (
                    _v(exception["exception_type"]),
                    _v(exception["severity"]),
                    _v(exception["rule_id"]),
                    _v(exception["status"]),
                    _v(exception["expected_value"]),
                    _v(exception["actual_value"]),
                    _v(exception["difference"]),
                    exception["ref"],
                )
            )

        match = inv["match"]

        out.append(
            "**PO / GRN facts (extracted reference ≠ matched record):**"
        )

        out.append(
            "- PO reference stored on invoice: %s; from extraction: %s" %
            (
                _v(match["po_reference_stored_on_invoice"]),
                _v(match["po_reference_from_extraction"]),
            )
        )

        out.append(
            "- PO master record found: %s" %
            (
                "not applicable (no reference)"
                if match["po_master_record_found"] is None
                else "yes"
                if match["po_master_record_found"]
                else "**no**"
            )
        )

        out.append(
            "- GRN reference stored on invoice: %s; from extraction: %s" %
            (
                _v(match["grn_reference_stored_on_invoice"]),
                _v(match["grn_reference_from_extraction"]),
            )
        )

        out.append(
            "- GRN master record found: %s" %
            (
                "not applicable (no reference)"
                if match["grn_master_record_found"] is None
                else "yes"
                if match["grn_master_record_found"]
                else "**no**"
            )
        )

        out.append(
            "- A reference appearing on the invoice does not by itself "
            "mean a valid master record was found or that the invoice "
            "was matched. Matching conclusions are those of the "
            "platform findings above."
        )

        if inv["fields_status"] == "ok":

            bad = [
                field
                for field in inv["fields"]
                if field["missing"] or field["low_confidence"]
            ]

            out.append(
                "**Extraction:** %d fields retrieved; %d missing or "
                "low-confidence (confidence is not proof of correctness)." %
                (
                    len(inv["fields"]),
                    len(bad),
                )
            )

            for field in bad[:10]:
                out.append(
                    "- %s: %s (confidence %s via %s, page %s) `%s`" %
                    (
                        field["field_name"],
                        "MISSING"
                        if field["missing"]
                        else _v(field["value"]),
                        _v(field["confidence"]),
                        _v(field["confidence_method"]),
                        _v(field["page_number"]),
                        field["ref"],
                    )
                )

        elif inv["fields_status"] == "no_records":

            out.append(
                "**Extraction:** no extracted-field records "
                "were found for this invoice."
            )

        else:

            out.append(
                "**Extraction:** not shown (%s)." %
                (
                    "insufficient permission"
                    if inv["fields_status"] == "withheld_permission"
                    else "document belongs to another user"
                )
            )

        if inv.get("missing_header_fields"):
            out.append(
                "- Not recorded on the invoice header: %s" %
                ", ".join(inv["missing_header_fields"])
            )

        if inv.get("reviews"):
            review = inv["reviews"][0]

            out.append(
                "**Latest review decision:** %s%s" %
                (
                    _v(review["decision"]),
                    (
                        " — " + review["comment"]
                        if review.get("comment")
                        else ""
                    ),
                )
            )

        if inv.get("checkpoints"):
            out.append(
                "**Workflow checkpoints recorded:** %d" %
                len(inv["checkpoints"])
            )

        if inv.get("audit"):
            out.append(
                "**Audit trail (latest %d):** " %
                len(inv["audit"]) +
                "; ".join(
                    "%s by %s" %
                    (
                        audit["action"],
                        _v(audit["actor"]),
                    )
                    for audit in inv["audit"][:5]
                )
            )

        out.append("**What to verify:**")

        out += [
            "- " + step
            for step in _verify_steps(inv, ctx["vendors"])
        ]

    if not ctx["invoices"]:

        for vendor in ctx["vendors"]:
            out.append(
                "**Vendor:** %s (%s) — verification status: **%s**, "
                "active: %s. Tax ID on file: %s `%s`" %
                (
                    _v(vendor["name"]),
                    _v(vendor["vendor_code"]),
                    _v(vendor["verification_status"]),
                    _v(vendor["active"]),
                    _v(vendor["tax_id"]),
                    vendor["ref"],
                )
            )

        for po in ctx["pos"]:
            out.append(
                "**PO %s:** status %s, currency %s, order date %s, "
                "%d line(s) `%s`" %
                (
                    po["po_number"],
                    _v(po["status"]),
                    _v(po["currency"]),
                    _v(po["order_date"]),
                    len(po["lines"]),
                    po["ref"],
                )
            )

        for grn in ctx["grns"]:
            out.append(
                "**GRN %s:** linked PO %s, receipt date %s, "
                "%d line(s) `%s`" %
                (
                    grn["grn_number"],
                    _v(grn["po_number"]),
                    _v(grn["receipt_date"]),
                    len(grn["lines"]),
                    grn["ref"],
                )
            )

    if ctx["listing"]:

        out.append(
            "**Invoices matching the status filter (up to %d):**" %
            config.MAX_LIST
        )

        out += [
            "- %s | %s | %s | %s %s" %
            (
                _v(row["invoice_number"]),
                _v(row["vendor_name_raw"]),
                _v(row["status"]),
                _v(row["grand_total"]),
                _v(row["currency"]),
            )
            for row in ctx["listing"]
        ]

    if ctx["high_risk"]:

        out.append(
            "**Open high-severity findings (up to %d):**" %
            config.MAX_LIST
        )

        out += [
            "- %s: %s (rule %s, severity %s, status %s)" %
            (
                _v(row["invoice_number"]),
                _v(row["exception_type"]),
                _v(row["rule_id"]),
                _v(row["severity"]),
                _v(row["status"]),
            )
            for row in ctx["high_risk"]
        ]

    if ctx["report"]:

        out.append(
            "**Platform counts:** invoices by status " +
            json.dumps(ctx["report"]["invoices_by_status"]) +
            "; findings by severity " +
            json.dumps(ctx["report"]["exceptions_by_severity"])
        )

    if ctx["not_found"]:

        out.append(
            "**Not found:** no invoice, PO, GRN or vendor record "
            "matched: %s. (The lookup succeeded; the records do not "
            "exist or are not visible to you.)" %
            ", ".join(ctx["not_found"])
        )

    for note in ctx["notes"]:
        out.append("_Note: %s_" % note)

    return "\n".join(out)


# --------------------------------------------------------------- workspace

def workspace(ctx: Dict[str, Any]) -> Dict[str, Any]:

    inv = next(
        (
            invoice
            for invoice in ctx["invoices"]
            if "exceptions" in invoice
        ),
        None,
    )

    if inv is None:
        return {
            "invoice": None,
            "findings": [],
            "extraction": [],
            "match_info": None,
            "verify_steps": [],
        }

    return {
        "invoice": {
            key: inv.get(key)
            for key in (
                "invoice_number",
                "status",
                "vendor_name_raw",
                "grand_total",
                "currency",
                "invoice_date",
                "po_number",
                "grn_number",
            )
        },
        "findings": inv["exceptions"],
        "extraction": [
            field
            for field in inv["fields"]
            if field["missing"] or field["low_confidence"]
        ][:20],
        "match_info": inv["match"],
        "verify_steps": _verify_steps(inv, ctx["vendors"]),
    }


# ------------------------------------------------------- general answers

def _general_answer(
    question: str,
    provider: Any,
    timeout: float,
    call: Callable[..., Optional[str]],
    history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Answer a general question without database retrieval."""

    try:
        user_prompt = build_general_user_prompt(
            question,
            history=history,
        )

        raw = call(
            provider,
            GENERAL_SYSTEM_PROMPT,
            user_prompt,
            timeout,
        )

    except Exception as exc:
        reason = _classify_llm_error(exc)

        log.warning(
            "copilot general llm failure category=%s",
            reason,
        )

        return {
            "answer": _general_notice(reason),
            "mode": "general_fallback",
            "model_available": False,
            "evidence": [],
            "retrieved": {},
            "warnings": [reason],
            "invoice": None,
            "findings": [],
            "extraction": [],
            "match_info": None,
            "verify_steps": [],
        }

    if raw is None or (
        isinstance(raw, str) and not raw.strip()
    ):
        reason = "model_empty"
        cleaned = None
    else:
        ok, cleaned, why = validate_general_output(raw)

        if not ok:
            reason = "invalid_output:" + why
            cleaned = None
        else:
            reason = ""

    if cleaned:
        return {
            "answer": cleaned,
            "mode": "general_llm",
            "model_available": True,
            "evidence": [],
            "retrieved": {},
            "warnings": [],
            "invoice": None,
            "findings": [],
            "extraction": [],
            "match_info": None,
            "verify_steps": [],
        }

    log.warning(
        "copilot general output rejected reason=%s",
        reason,
    )

    return {
        "answer": _general_notice(reason),
        "mode": "general_fallback",
        "model_available": False,
        "evidence": [],
        "retrieved": {},
        "warnings": [reason],
        "invoice": None,
        "findings": [],
        "extraction": [],
        "match_info": None,
        "verify_steps": [],
    }


def _general_notice(reason: str) -> str:

    if reason == "model_timeout":
        return GENERAL_NOTICE_TIMEOUT

    if reason == "model_empty":
        return GENERAL_NOTICE_EMPTY

    if reason.startswith("invalid_output"):
        return GENERAL_NOTICE_INVALID

    return GENERAL_NOTICE_UNAVAILABLE


# ------------------------------------------------------------------ answer

def answer(
    question: str,
    ctx: Dict[str, Any],
    scope: Scope,
    provider: Any,
    timeout: float,
    llm_call: Optional[Callable[..., Optional[str]]] = None,
    general: bool = False,
    history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:

    # Step 1: Handle simple questions without calling the LLM.

    simple_response = _simple_response(question)

    if simple_response:
        return {
            "answer": simple_response,
            "mode": "instant_response",
            "model_available": False,
            "evidence": [],
            "retrieved": {},
            "warnings": [],
            "invoice": None,
            "findings": [],
            "extraction": [],
            "match_info": None,
            "verify_steps": [],
        }

    # Step 2: Prepare the existing provider call and bounded timeout.

    call = llm_call or default_llm_call

    timeout = min(
        float(timeout or config.COPILOT_MAX_LLM_SECONDS),
        config.COPILOT_MAX_LLM_SECONDS,
    )

    # Step 3: General questions use Qwen without database facts.

    if general:
        return _general_answer(
            question=question,
            provider=provider,
            timeout=timeout,
            call=call,
            history=history,
        )

    warnings: List[str] = []

    base = {
        "evidence": ctx.get("evidence", []),
        "retrieved": ctx.get("counts", {}),
        "warnings": warnings,
        "model_available": False,
        "invoice": None,
        "findings": [],
        "extraction": [],
        "match_info": None,
        "verify_steps": [],
    }

    # Step 4: Handle platform help questions.

    if not has_data(ctx):

        intents = ctx.get("intents") or {}
        tokens = ctx.get("tokens") or []

        if intents.get("howto") and not tokens:

            system = HOWTO_SYSTEM_PROMPT
            data = help_text(scope.role)

            text, reason = _ask(
                call,
                provider,
                system,
                build_user_prompt(question, data),
                timeout,
                data,
                question,
            )

            if text:
                return {
                    **base,
                    "answer": text,
                    "mode": "facts+llm",
                    "model_available": True,
                }

            return {
                **base,
                "answer": (
                    help_text(scope.role)
                    + "\n\n"
                    + _notice(reason)
                ),
                "mode": "facts_only",
                "warnings": [reason],
            }

        message = (
            render_facts(ctx, scope)
            if ctx.get("not_found") or ctx.get("notes")
            else ""
        )

        if not message:
            message = (
                "I couldn't identify a record to look up. "
                "Please include an invoice number, PO number, "
                "GRN number or vendor code "
                '(for example: "Why was invoice INV-2026-00085 flagged?").'
            )

        return {
            **base,
            "answer": message,
            "mode": "not_found",
        }

    # Step 5: Build deterministic facts from retrieved records.

    facts = render_facts(ctx, scope)

    base.update(workspace(ctx))

    data = render_context_text(ctx)

    # Step 6: Call the configured LLM provider.

    text, reason = _ask(
        call,
        provider,
        SYSTEM_PROMPT,
        build_user_prompt(question, data),
        timeout,
        data,
        question,
    )

    # Step 7: Return facts plus validated AI explanation.

    if text:

        return {
            **base,
            "answer": (
                facts
                + "\n\n"
                + "**AI explanation (checked against the data above):**\n"
                + text
            ),
            "mode": "facts+llm",
            "model_available": True,
        }

    # Step 8: Safe fallback when LLM fails validation or times out.

    warnings.append(reason)

    return {
        **base,
        "answer": facts + "\n\n" + _notice(reason),
        "mode": "facts_only",
    }


# --------------------------------------------------------------- notices

def _notice(reason: str) -> str:

    if reason == "model_empty":
        return NOTICE_EMPTY

    if reason == "model_timeout":
        return NOTICE_TIMEOUT

    if reason == "model_unavailable":
        return NOTICE_UNAVAILABLE

    if reason.startswith("invalid"):
        return NOTICE_INVALID

    return NOTICE_UNAVAILABLE


# --------------------------------------------------------------- LLM call

def _ask(
    call,
    provider,
    system,
    user,
    timeout,
    grounding,
    question,
):
    """Return strictly validated financial LLM text or a safe failure."""

    try:
        raw = call(
            provider,
            system,
            user,
            timeout,
        )

    except Exception as exc:

        reason = _classify_llm_error(exc)

        log.warning(
            "copilot llm failure category=%s",
            reason,
        )

        return None, reason

    if raw is None or (
        isinstance(raw, str) and not raw.strip()
    ):
        return None, "model_empty"

    if not isinstance(raw, str):
        return None, "invalid_output:not_text"

    ok, cleaned, why = validate_output(
        raw,
        grounding + " " + question,
    )

    if not ok:

        log.warning(
            "copilot llm output rejected reason=%s",
            why,
        )

        return None, f"invalid_output:{why}"

    return cleaned, ""