
"""Streamlit UI for the authenticated, read-only Financial Risk Copilot.

Call render_copilot() once from app.py after authentication and before nav.run().
"""
from __future__ import annotations

from typing import Any, Dict, List


WELCOME = (
    "Hello! I'm your Financial Risk Copilot. I can answer general questions, "
    "explain financial concepts, help with Python and programming, and "
    "investigate invoices, vendors, purchase orders, GRNs, risk findings "
    "and workflow status using your authorized platform data. "
    "I'm read-only and cannot approve, reject or modify records. "
    "What would you like to know?"
)

SUBTITLE = "General AI + Financial Records | Read-only | Qwen 2.5"

EXAMPLES = [
    "What can you help me with?",
    "What is three-way matching?",
    "Explain invoice processing step by step.",
    "Explain Python decorators with an example.",
    "Why was invoice INV-2026-00085 rejected?",
    "Show the missing extraction fields for this invoice.",
    "What are the high-risk findings?",
    "Explain the GRN mismatch.",
    "Show invoices pending review.",
    "What should I manually verify before approval?",
]

K_MSGS, K_UID, K_EXP, K_INV, K_PEND = (
    "apc_msgs",
    "apc_uid",
    "apc_expanded",
    "apc_invoice",
    "apc_pending",
)

_ALL_KEYS = (K_MSGS, K_UID, K_EXP, K_INV, K_PEND)


_CSS = """
<style>
/* =========================================================
   1. DESIGN TOKENS
========================================================= */

:root {
    --cp-bg: #090E1C;
    --cp-surface: #111A2E;
    --cp-card: #16213A;
    --cp-card-user: #1A2F55;
    --cp-input: #0F1829;

    --cp-border: #2A3A57;
    --cp-border-soft: rgba(148, 163, 184, 0.18);

    --cp-text: #E8EEF7;
    --cp-text-strong: #FFFFFF;
    --cp-muted: #9FB0C7;

    --cp-accent: #4F8DF7;
    --cp-accent-2: #6D7BF5;
    --cp-hover: #1F2F4F;
    --cp-code-bg: #0A101D;
}

/* =========================================================
   2. FLOATING LAUNCHER BUTTON
========================================================= */

.st-key-ap_copilot_fab {
    position: fixed;
    bottom: 1.25rem;
    right: 1.25rem;
    z-index: 999;
    width: auto !important;
}

.st-key-ap_copilot_fab button {
    border-radius: 999px !important;
    padding: 0.65rem 1.2rem !important;
    font-weight: 650 !important;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35) !important;
    transition: transform 0.15s ease, box-shadow 0.15s ease !important;
}

.st-key-ap_copilot_fab button:hover {
    transform: translateY(-1px);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45) !important;
}

/* =========================================================
   3. POPOVER AND EXPANDED DIALOG BACKGROUNDS
========================================================= */

div[data-testid="stPopoverBody"] {
    width: min(470px, 94vw);
    max-height: 82vh;
    overflow-y: auto;
    background: var(--cp-bg) !important;
}

div[data-testid="stDialog"] div[role="dialog"] {
    background: var(--cp-bg) !important;
    background-color: var(--cp-bg) !important;
    border: 1px solid var(--cp-border-soft) !important;
    border-radius: 18px !important;
    color: var(--cp-text) !important;
}

/* Keep dialog wrappers transparent */
div[data-testid="stDialog"] > div,
div[data-testid="stDialog"] div[role="dialog"] > div {
    background-color: transparent !important;
}

/* Popover background */
div[data-testid="stPopoverBody"] {
    background: var(--cp-bg) !important;
    color: var(--cp-text) !important;
    border: 1px solid var(--cp-border-soft) !important;
    border-radius: 18px !important;
}

/* =========================================================
   4. GENERAL TEXT
========================================================= */

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) :is(
    p, li, label, h1, h2, h3, h4, h5, h6
) {
    color: var(--cp-text) !important;
}

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stMarkdownContainer"] {
    color: var(--cp-text) !important;
}

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stCaptionContainer"],
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) small {
    color: var(--cp-muted) !important;
}

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) hr {
    border-color: var(--cp-border-soft) !important;
}

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) a {
    color: #8DB8FF !important;
}

/* =========================================================
   5. CHAT MESSAGE CARDS
========================================================= */

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stChatMessage"] {
    background: var(--cp-card) !important;
    background-color: var(--cp-card) !important;
    border: 1px solid var(--cp-border) !important;
    border-radius: 14px !important;
    padding: 0.85rem 1rem !important;
    margin-bottom: 0.75rem !important;
    box-shadow: 0 3px 10px rgba(0, 0, 0, 0.20) !important;
    color: var(--cp-text) !important;
}

/* User message card */
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stChatMessage"]:has(
    [data-testid="stChatMessageAvatarUser"]
) {
    background: var(--cp-card-user) !important;
    background-color: var(--cp-card-user) !important;
    border-color: #2F4A7D !important;
}

/* Remove unwanted white inner backgrounds */
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stChatMessage"] > div,
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stChatMessageContent"],
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"],
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stChatMessage"] [data-testid="stVerticalBlock"] {
    background: transparent !important;
    background-color: transparent !important;
}

/* Chat answer text */
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stChatMessage"] :is(
    p, li, ol, ul, em, td, th,
    h1, h2, h3, h4, h5, h6
) {
    color: var(--cp-text) !important;
    -webkit-text-fill-color: var(--cp-text) !important;
    line-height: 1.7 !important;
    overflow-wrap: anywhere;
}

/* Bold text */
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stChatMessage"] strong {
    color: var(--cp-text-strong) !important;
    -webkit-text-fill-color: var(--cp-text-strong) !important;
    font-weight: 650 !important;
}

/* User and assistant message text */
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stChatMessage"] span {
    color: var(--cp-text) !important;
    -webkit-text-fill-color: var(--cp-text) !important;
}

/* =========================================================
   6. CODE BLOCKS
========================================================= */

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stChatMessage"] pre {
    background: var(--cp-code-bg) !important;
    background-color: var(--cp-code-bg) !important;
    border: 1px solid var(--cp-border) !important;
    border-radius: 10px !important;
    color: #E8EEF7 !important;
}

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stChatMessage"] code {
    background: var(--cp-code-bg) !important;
    color: #C7D7F0 !important;
    -webkit-text-fill-color: #C7D7F0 !important;
    border-radius: 6px;
}

/* =========================================================
   7. TABLES INSIDE CHAT
========================================================= */

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stChatMessage"] table {
    border-collapse: collapse !important;
    color: var(--cp-text) !important;
}

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stChatMessage"] :is(th, td) {
    border: 1px solid var(--cp-border) !important;
    background: transparent !important;
    color: var(--cp-text) !important;
    padding: 0.4rem 0.6rem !important;
}

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stChatMessage"] th {
    background: rgba(79, 141, 247, 0.12) !important;
}

/* =========================================================
   8. CHAT AVATARS
========================================================= */

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stChatMessageAvatarAssistant"] {
    background: linear-gradient(
        135deg,
        var(--cp-accent),
        var(--cp-accent-2)
    ) !important;
}

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stChatMessageAvatarUser"] {
    background: #334A75 !important;
}

/* =========================================================
   9. INVESTIGATION PANEL AND BORDERED CONTAINERS
========================================================= */

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--cp-surface) !important;
    background-color: var(--cp-surface) !important;
    border: 1px solid var(--cp-border) !important;
    border-radius: 14px !important;
}

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stVerticalBlockBorderWrapper"] > div {
    background: transparent !important;
}

/* Investigation panel text */
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stVerticalBlockBorderWrapper"] :is(
    p, span, label, h1, h2, h3, h4
) {
    color: var(--cp-text) !important;
    -webkit-text-fill-color: var(--cp-text) !important;
}

/* =========================================================
   10. EXPANDERS AND ALERTS
========================================================= */

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stExpander"],
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stExpander"] details {
    background: var(--cp-surface) !important;
    border: 1px solid var(--cp-border) !important;
    border-radius: 12px !important;
}

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stExpander"] summary,
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stExpander"] summary * {
    color: var(--cp-text) !important;
}

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stAlert"] {
    background: var(--cp-surface) !important;
    border: 1px solid var(--cp-border) !important;
    border-radius: 12px !important;
}

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stAlert"] * {
    color: var(--cp-text) !important;
}

/* =========================================================
   11. METRICS
========================================================= */

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stMetric"] * {
    color: var(--cp-text) !important;
}

/* =========================================================
   12. HEADER
========================================================= */

.copilot-heading {
    font-size: 1.15rem;
    font-weight: 750;
    letter-spacing: -0.02em;
    color: #F8FAFC !important;
}

.copilot-subtitle {
    font-size: 0.76rem;
    color: var(--cp-muted) !important;
    margin-top: 0.2rem;
}

.copilot-example-label {
    font-size: 0.8rem;
    font-weight: 650;
    margin: 0.9rem 0 0.5rem;
    color: var(--cp-muted) !important;
}

/* =========================================================
   13. BUTTONS
========================================================= */

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) button {
    min-height: 2.3rem;
    border-radius: 999px !important;
    font-weight: 550 !important;
    box-shadow: none !important;
    transform: none !important;
    transition: background 0.18s ease, border-color 0.18s ease !important;
}

/* Secondary buttons */
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) button[kind="secondary"] {
    background: var(--cp-card) !important;
    border: 1px solid var(--cp-border) !important;
    color: var(--cp-text) !important;
}

/* Secondary button hover */
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) button[kind="secondary"]:hover,
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) button[kind="secondary"]:focus,
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) button[kind="secondary"]:focus-visible,
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) button[kind="secondary"]:active {
    background: var(--cp-hover) !important;
    border-color: var(--cp-accent) !important;
    color: var(--cp-text-strong) !important;
    outline: none !important;
}

/* Primary buttons */
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) button[kind="primary"] {
    background: linear-gradient(
        135deg,
        var(--cp-accent),
        var(--cp-accent-2)
    ) !important;
    border: none !important;
    color: #FFFFFF !important;
    font-weight: 650 !important;
}

/* Primary button hover */
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) button[kind="primary"]:hover {
    filter: brightness(1.1);
}

/* Disabled buttons */
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) button:disabled {
    opacity: 0.5 !important;
}

/* Button text */
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) button :is(p, span, div) {
    color: inherit !important;
}

/* =========================================================
   14. CHAT COMPOSER
========================================================= */

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) div[data-testid="stForm"] {
    background: var(--cp-surface) !important;
    border: 1px solid var(--cp-border) !important;
    border-radius: 16px !important;
    padding: 0.7rem !important;
}

/* Input wrappers */
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) :is(
    [data-baseweb="input"],
    [data-baseweb="base-input"],
    [data-baseweb="textarea"]
) {
    background: var(--cp-input) !important;
    background-color: var(--cp-input) !important;
    border-color: var(--cp-border) !important;
    border-radius: 12px !important;
}

/* Input text */
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) :is(input, textarea) {
    background: var(--cp-input) !important;
    color: var(--cp-text-strong) !important;
    caret-color: var(--cp-text-strong) !important;
    -webkit-text-fill-color: var(--cp-text-strong) !important;
}

/* Input placeholder */
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) :is(input, textarea)::placeholder {
    color: var(--cp-muted) !important;
    -webkit-text-fill-color: var(--cp-muted) !important;
    opacity: 1 !important;
}

/* Input focus */
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-baseweb="input"]:focus-within,
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-baseweb="base-input"]:focus-within {
    border-color: var(--cp-accent) !important;
    box-shadow: 0 0 0 1px var(--cp-accent) !important;
}

/* Streamlit chat input */
:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stChatInput"] {
    background: var(--cp-input) !important;
    border: 1px solid var(--cp-border) !important;
    border-radius: 14px !important;
}

/* =========================================================
   15. SCROLLBARS
========================================================= */

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) ::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) ::-webkit-scrollbar-thumb {
    background: #33445F;
    border-radius: 8px;
}

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) ::-webkit-scrollbar-track {
    background: transparent;
}

/* =========================================================
   16. SPINNER
========================================================= */

:is(
    div[data-testid="stPopoverBody"],
    div[data-testid="stDialog"]
) [data-testid="stSpinner"] * {
    color: var(--cp-muted) !important;
}

/* =========================================================
   17. RESPONSIVE DESIGN
========================================================= */

@media (max-width: 700px) {
    div[data-testid="stPopoverBody"] {
        width: 94vw;
    }

    :is(
        div[data-testid="stPopoverBody"],
        div[data-testid="stDialog"]
    ) [data-testid="stChatMessage"] {
        padding: 0.7rem 0.8rem !important;
    }
}

/* =========================================================
   18. REDUCED MOTION
========================================================= */

@media (prefers-reduced-motion: reduce) {
    :is(
        div[data-testid="stPopoverBody"],
        div[data-testid="stDialog"]
    ) button,
    .st-key-ap_copilot_fab button {
        transition: none !important;
    }
}

</style>
"""




def _reset(st) -> None:
    for key in _ALL_KEYS:
        st.session_state.pop(key, None)


def clear_copilot_state() -> None:
    """Clear Copilot session data when the user signs out."""
    import streamlit as st
    _reset(st)


def _post_chat(payload):
    from ui.state import api
    client = api()
    return client.post("/api/copilot/chat", payload)


def _error_text(exc: Exception) -> str:
    try:
        from ui.api_client import ApiProblem, Unauthorized, Unreachable

        if isinstance(exc, Unauthorized):
            return "Your session has expired. Please sign in again."

        if isinstance(exc, Unreachable):
            return "The platform API is unreachable right now."

        if isinstance(exc, ApiProblem):
            return (
                "The Copilot request was not accepted: %s"
                % str(exc)[:200]
            )

    except Exception:
        pass

    return "The Copilot could not complete the request."


def _bounded_history(
    messages: List[Dict[str, Any]]
) -> List[Dict[str, str]]:
    """Return only the last eight valid user/assistant messages."""

    history = []

    for message in messages[-8:]:
        role = message.get("role")
        content = message.get("content")

        if role not in ("user", "assistant"):
            continue

        if not isinstance(content, str):
            continue

        content = content.strip()

        if not content:
            continue

        history.append({
            "role": role,
            "content": content[:1500],
        })

    return history


def _send(st, question: str) -> None:
    msgs: List[Dict[str, Any]] = st.session_state.setdefault(
        K_MSGS, []
    )

    question = question.strip()

    if not question:
        return

    msgs.append({
        "role": "user",
        "content": question,
    })

    payload = {
        "question": question,
        "history": _bounded_history(msgs[:-1]),
    }

    with st.spinner("Copilot is thinking..."):
        try:
            res = _post_chat(payload)

        except Exception as exc:
            msgs.append({
                "role": "assistant",
                "content": _error_text(exc),
                "meta": None,
            })
            return

    res = res or {}
    invoice = res.get("invoice") or {}

    if invoice.get("invoice_number"):
        st.session_state[K_INV] = invoice["invoice_number"]

    msgs.append({
        "role": "assistant",
        "content": res.get(
            "answer",
            "I couldn't generate an answer."
        ),
        "meta": res,
    })


def _workspace_panel(st, meta: Dict[str, Any]) -> None:
    """Show only information returned by the backend."""

    st.markdown("#### Investigation")

    inv = meta.get("invoice") if meta else None

    if not inv:
        st.caption(
            "Ask about a specific invoice to see its findings, "
            "extraction details and matching facts here."
        )
        return

    st.markdown(
        "**%s** — %s"
        % (
            inv.get("invoice_number"),
            inv.get("status"),
        )
    )

    st.caption(
        "Vendor on invoice: %s | %s %s"
        % (
            inv.get("vendor_name_raw"),
            inv.get("grand_total"),
            inv.get("currency"),
        )
    )

    if meta.get("findings"):
        st.markdown("**Risk findings**")

        st.dataframe(
            [
                {
                    key: finding.get(key)
                    for key in (
                        "exception_type",
                        "severity",
                        "rule_id",
                        "status",
                        "expected_value",
                        "actual_value",
                        "difference",
                        "ref",
                    )
                }
                for finding in meta["findings"]
            ],
            hide_index=True,
            use_container_width=True,
        )

    if meta.get("extraction"):
        st.markdown("**Missing / low-confidence extraction**")

        st.dataframe(
            [
                {
                    key: field.get(key)
                    for key in (
                        "field_name",
                        "value",
                        "confidence",
                        "confidence_method",
                        "page_number",
                        "missing",
                        "ref",
                    )
                }
                for field in meta["extraction"]
            ],
            hide_index=True,
            use_container_width=True,
        )

    if meta.get("match_info"):
        st.markdown("**PO / GRN facts**")

        st.json(
            {
                key: value
                for key, value in meta["match_info"].items()
                if key != "platform_findings_about_po_grn"
            },
            expanded=False,
        )

    if meta.get("verify_steps"):
        st.markdown("**Recommended verification**")

        for step in meta["verify_steps"]:
            st.markdown("- " + step)

    if meta.get("evidence"):
        with st.expander(
            "Evidence references (%d)" % len(meta["evidence"])
        ):
            for evidence in meta["evidence"]:
                st.markdown(
                    "- `%s` — %s"
                    % (
                        evidence.get("ref"),
                        evidence.get("label"),
                    )
                )


def _chat_header(st, expanded: bool) -> None:
    if expanded:
        top = st.columns([4, 1, 1, 1])
    else:
        top = st.columns([3, 1, 1])

    with top[0]:
        st.markdown(
            '<div class="copilot-heading">Financial Risk Copilot</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="copilot-subtitle">%s</div>'
            % SUBTITLE,
            unsafe_allow_html=True,
        )

    if top[1].button(
        "Collapse" if expanded else "Expand",
        key="apc_exp_%s" % expanded,
        help="Toggle the larger investigation workspace",
        use_container_width=True,
        type="secondary",
    ):
        st.session_state[K_EXP] = not expanded
        st.rerun()

    if top[2].button(
        "Clear",
        key="apc_clear_%s" % expanded,
        help="Clear this conversation",
        use_container_width=True,
        type="secondary",
    ):
        st.session_state[K_MSGS] = []
        st.session_state.pop(K_INV, None)
        st.rerun()

    if expanded and top[3].button(
        "Close",
        key="apc_close",
        use_container_width=True,
        type="secondary",
    ):
        st.session_state[K_EXP] = False
        st.rerun()


def _chat_body(st, expanded: bool) -> None:
    _chat_header(st, expanded)

    pending = st.session_state.pop(K_PEND, None)
    msgs = st.session_state.setdefault(K_MSGS, [])

    if expanded:
        chat_col, side_col = st.columns(
            [3, 2],
            gap="large",
        )
    else:
        chat_col = st.container()
        side_col = None

    # IMPORTANT:
    # Do not create another container with key="ap_copilot_fab"
    # here. render_copilot() creates that launcher container once.

    with chat_col:
        if not msgs:
            with st.chat_message("assistant"):
                st.markdown(WELCOME)

            st.markdown(
                '<div class="copilot-example-label">Try asking</div>',
                unsafe_allow_html=True,
            )

            example_count = 10 if expanded else 4

            for index, example in enumerate(
                EXAMPLES[:example_count]
            ):
                if st.button(
                    example,
                    key="apc_ex_%s_%d" % (expanded, index),
                    use_container_width=True,
                    type="secondary",
                ):
                    pending = example

        if pending:
            _send(st, pending)
            msgs = st.session_state[K_MSGS]

        # Conversation history above the composer.
        for message in msgs:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        st.markdown("---")

        # Composer stays at the bottom of the conversation.
        with st.form(
            "apc_form_%s" % expanded,
            clear_on_submit=True,
        ):
            text = st.text_input(
                "Ask",
                placeholder=(
                    "Ask anything or investigate an invoice, PO, GRN or vendor..."
                ),
                max_chars=1000,
                label_visibility="collapsed",
            )

            sent = st.form_submit_button(
                "Send",
                use_container_width=True,
            )

        if sent and text.strip():
            _send(st, text.strip())
            st.rerun()

    if side_col is not None:
        with side_col:
            last = next(
                (
                    message.get("meta")
                    for message in reversed(msgs)
                    if message["role"] == "assistant"
                ),
                None,
            )

            with st.container(border=True):
                _workspace_panel(st, last or {})


def _workspace_dialog(st):
    dialog_api = (
        getattr(st, "dialog", None)
        or getattr(st, "experimental_dialog", None)
    )

    if dialog_api is None:
        return None

    try:
        decorate = dialog_api(
            "Financial Risk Copilot — Investigation workspace",
            width="large",
        )
    except TypeError:
        decorate = dialog_api(
            "Financial Risk Copilot — Investigation workspace"
        )

    @decorate
    def _open():
        _chat_body(st, expanded=True)

    return _open


def render_copilot() -> None:
    import streamlit as st

    from backend.auth.permissions import can
    from ui.state import user

    current_user = user()

    if not current_user or not can(
        current_user.get("role"),
        "view_records",
    ):
        _reset(st)
        return

    uid = current_user.get(
        "id",
        current_user.get("username"),
    )

    if st.session_state.get(K_UID) != uid:
        _reset(st)
        st.session_state[K_UID] = uid

    st.markdown(
        _CSS,
        unsafe_allow_html=True,
    )

    if st.session_state.get(K_EXP):
        dialog = _workspace_dialog(st)

        if dialog is not None:
            dialog()
            return

        st.session_state[K_EXP] = False

    if hasattr(st, "popover"):
        # This is the ONLY place where the launcher key is created.
        # _chat_body() must not create another container with this key.
        holder = st.container(key="ap_copilot_fab")

        with holder:
            try:
                popover = st.popover(
                    "Ask AI Copilot",
                    icon=":material/smart_toy:",
                )
            except TypeError:
                popover = st.popover("AI Copilot")

            with popover:
                _chat_body(st, expanded=False)

    else:
        with st.sidebar.expander("AI Copilot"):
            _chat_body(st, expanded=False)
