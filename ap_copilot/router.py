
"""POST /api/copilot/chat -- authenticated, read-only AI Copilot."""
from __future__ import annotations

import logging
import re
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.deps import get_session, require

from . import config
from .answer_service import answer
from .orm_repo import OrmRepo
from .schemas import ChatRequest, ChatResponse
from .retrieval import build_context
from .security import (
    InputRejected,
    build_scope,
    read_only_session,
    refusal_for,
    validate_question,
)

log = logging.getLogger("ap_copilot")

router = APIRouter(prefix="/api/copilot", tags=["copilot"])


_HINT_OK = re.compile(r"^[A-Za-z0-9._/\\-]{1,60}$")

# Explicit platform-record identifiers.
_RECORD_ID = re.compile(
    r"\b(?:INV|CASE|ALT|PO|GRN|MRN|VEN|VEND|MITRE)"
    r"[-_/]?[A-Z0-9][A-Z0-9._/-]*\b",
    re.IGNORECASE,
)

# Phrases that clearly ask about records inside this platform.
_RECORD_PHRASES = re.compile(
    r"\b(?:"
    r"this invoice|that invoice|my invoice|the invoice record|"
    r"invoice details|invoice status|invoice number|"
    r"latest invoices|recent invoices|pending invoices|"
    r"rejected invoices|approved invoices|overdue invoices|"
    r"high[- ]risk findings|risk findings for|"
    r"platform findings|platform records|"
    r"vendor status|vendor details|vendor record|"
    r"purchase order record|po status|po details|"
    r"goods receipt record|grn status|grn details|"
    r"three[- ]way match status|matching status|"
    r"reconciliation status|reconciliation report|"
    r"audit history|audit trail|review history|"
    r"workflow status|workflow history|"
    r"extraction results|extracted fields|"
    r"exception details|invoice exceptions|"
    r"show me (?:the )?(?:invoices?|vendors?|purchase orders?|grns?)|"
    r"find (?:the )?(?:invoice|vendor|purchase order|grn)|"
    r"look up (?:the )?(?:invoice|vendor|purchase order|grn)|"
    r"check (?:the )?(?:invoice|vendor|purchase order|grn)"
    r")\b",
    re.IGNORECASE,
)

# Follow-up questions that need the preceding record context.
_FOLLOWUP_PATTERN = re.compile(
    r"^\s*(?:"
    r"why|how|what about|explain|tell me more|"
    r"what does that mean|what does this mean|"
    r"and then|what next|what should i check|"
    r"which finding|which field|"
    r"can you explain|elaborate"
    r")\b",
    re.IGNORECASE,
)

# Explicit general-education questions should not trigger record retrieval.
_GENERAL_EDUCATION = re.compile(
    r"\b(?:"
    r"what is|what are|explain|define|teach me|"
    r"how does|how do|difference between|"
    r"meaning of|give me an example of|"
    r"write|draft|rewrite|summarize|"
    r"help me learn|"
    r"what is the purpose of"
    r")\b",
    re.IGNORECASE,
)

# A specific identifier or a platform phrase takes priority over general
# educational wording. This avoids treating "explain this invoice" as theory.
def _is_record_question(
    question: str,
    history: list,
    invoice_hint: str | None = None,
) -> bool:
    """Classify record lookups using explicit phrases and recent context."""

    q = question.strip()

    if invoice_hint:
        return True

    if _RECORD_ID.search(q):
        return True

    if _RECORD_PHRASES.search(q):
        return True

    # "Explain this" or "why?" inherits record intent only when a recent
    # conversation message clearly referred to a platform record.
    if _FOLLOWUP_PATTERN.search(q):
        for message in reversed(history[-8:]):
            content = (
                message.content
                if hasattr(message, "content")
                else message.get("content", "")
            )
            role = (
                message.role
                if hasattr(message, "role")
                else message.get("role", "")
            )

            if role not in ("user", "assistant"):
                continue

            if _RECORD_ID.search(content or ""):
                return True

            if _RECORD_PHRASES.search(content or ""):
                return True

    # General educational wording such as "What is a vendor?" or
    # "Explain three-way matching" stays on the general AI path.
    if _GENERAL_EDUCATION.search(q):
        return False

    return False


def _history_for_answer(body: ChatRequest) -> list:
    """Convert validated Pydantic messages into bounded prompt history."""

    result = []

    for message in body.history[-8:]:
        content = message.content.strip()[:1500]

        if not content:
            continue

        result.append({
            "role": message.role,
            "content": content,
        })

    return result


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    request: Request,
    user=Depends(require("view_records")),
    db=Depends(get_session),
):
    t0 = time.monotonic()

    rid = (
        request.headers.get("x-request-id") or uuid.uuid4().hex
    )[:64]

    # Step 1: Validate the current question.
    try:
        question = validate_question(body.question)

    except InputRejected as exc:
        log.info(
            "copilot rejected request_id=%s code=%s",
            rid,
            exc.code,
        )
        raise HTTPException(
            status_code=400,
            detail=exc.message,
        )

    # Step 2: Apply existing security refusals before model or database use.
    refusal = refusal_for(question)

    if refusal:
        log.info(
            "copilot refused request_id=%s user=%s",
            rid,
            user.id,
        )

        return ChatResponse(
            answer=refusal,
            mode="refused",
            request_id=rid,
        )

    # Step 3: Prepare the user's authorized scope and bounded history.
    scope = build_scope(user.role)
    history = _history_for_answer(body)

    hint = (
        body.invoice_number.strip()
        if body.invoice_number
        and _HINT_OK.fullmatch(body.invoice_number.strip())
        else None
    )

    # Step 4: Select general AI or platform-record retrieval.
    record_question = _is_record_question(
        question,
        history,
        hint,
    )

    # Step 5: Read application provider and timeout settings.
    settings = getattr(
        request.app.state,
        "settings",
        None,
    )

    timeout = getattr(
        settings,
        "llm_timeout_seconds",
        config.COPILOT_MAX_LLM_SECONDS,
    )

    provider = getattr(
        request.app.state,
        "provider",
        None,
    )

    # Step 6: General questions do not access the database.
    if not record_question:
        result = answer(
            question,
            {},
            scope,
            provider,
            timeout,
            general=True,
            history=history,
        )

        log.info(
            "copilot ok request_id=%s user=%s mode=%s ms=%d route=general warnings=%s",
            rid,
            user.id,
            result["mode"],
            int((time.monotonic() - t0) * 1000),
            result.get("warnings"),
        )

        return ChatResponse(
            request_id=rid,
            **result,
        )

    # Step 7: Retrieve authorized platform records using read-only access.
    try:
        with read_only_session(db):
            ctx = build_context(
                OrmRepo(db, user.id, user.role),
                scope,
                question,
                hint,
            )

    except Exception as exc:
        log.error(
            "copilot retrieval failed request_id=%s category=%s",
            rid,
            type(exc).__name__,
        )

        return ChatResponse(
            answer=(
                "I can't retrieve live platform information right now, "
                "so I can't answer this safely. Please try again shortly."
            ),
            mode="unavailable",
            warnings=["retrieval_failed"],
            request_id=rid,
        )

    # Step 8: Generate a grounded financial answer.
    result = answer(
        question,
        ctx,
        scope,
        provider,
        timeout,
        history=history,
    )

    # Step 9: Log request metadata without logging question or record content.
    log.info(
        "copilot ok request_id=%s user=%s mode=%s ms=%d route=records retrieved=%s warnings=%s",
        rid,
        user.id,
        result["mode"],
        int((time.monotonic() - t0) * 1000),
        result.get("retrieved"),
        result.get("warnings"),
    )

    return ChatResponse(
        request_id=rid,
        **result,
    )
