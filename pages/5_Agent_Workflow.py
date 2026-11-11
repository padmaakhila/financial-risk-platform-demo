
import streamlit as st

from backend.auth.permissions import can
from ui.components import (
    document_preview,
    explanation_panel,
    fields_table,
    findings_view,
    invoice_header,
    job_progress,
    lines_table,
    table,
)
from ui.format import group_exceptions, money, status_label
from ui.state import api, call, header, require_login


# ---------------------------------------------------------
# PAGE ACCESS
# ---------------------------------------------------------

u = require_login("view_records")
st.markdown("""
<style>
/* Agent Workflow invoice summary card text */
div[data-testid="stMetricValue"] {
    font-size: 15px !important;
    font-weight: 400 !important;
    line-height: 1.35 !important;
}

div[data-testid="stMetricLabel"] {
    font-size: 13px !important;
    font-weight: 400 !important;
    white-space: normal !important;
}
</style>
""", unsafe_allow_html=True)
header(
    "AI / Agent Workflow",
    "Track invoice processing, extraction, validation, "
    "risk explanation, verification and human review."
)


# ---------------------------------------------------------
# INVOICE SEARCH AND FILTERS
# ---------------------------------------------------------

st.subheader("Invoice selection")

c1, c2 = st.columns([2, 1], gap="medium")

with c1:
    q = st.text_input(
        "Find an invoice",
        placeholder="Search by invoice number, vendor or PO...",
        key="wf_q",
    )

with c2:
    status = st.selectbox(
        "Filter by status",
        [
            "(any)",
            "RECEIVED",
            "PROCESSING",
            "AWAITING_REVIEW",
            "NEEDS_MANUAL_ENTRY",
            "FAILED",
            "APPROVED",
            "REJECTED",
            "PAID",
        ],
        key="wf_status",
    )


res = call(
    api().get,
    "/api/invoices",
    q=q or None,
    status=None if status == "(any)" else status,
    limit=100,
)

if not res or not res["items"]:
    st.info("No invoices match your search or selected status.")
    st.stop()

items = res["items"]

inv_id = st.selectbox(
    "Select invoice",
    [i["id"] for i in items],
    key="wf_pick",
    format_func=lambda x: next(
        (
            f"{i['invoice_number']} | {i['vendor']} | "
            f"{money(i['grand_total'], i['currency'])} | "
            f"{status_label(i['status'])}"
        )
        for i in items
        if i["id"] == x
    ),
)

detail = call(
    api().get,
    f"/api/invoices/{inv_id}",
)

if detail is None:
    st.stop()


# ---------------------------------------------------------
# INVOICE DETAILS
# ---------------------------------------------------------

st.divider()
st.subheader("Selected invoice")

invoice_header(detail)


# ---------------------------------------------------------
# WORKFLOW ACTION
# ---------------------------------------------------------

if can(u["role"], "process"):
    st.markdown("### Workflow action")

    st.caption(
        "Run the invoice workflow to perform vendor verification, "
        "matching, risk explanation, verification and review hand-off."
    )

    if st.button(
        "Process / re-process this invoice",
        key="wf_process_invoice",
        type="primary",
        use_container_width=False,
        help=(
            "Queues the workflow: vendor check, matching, "
            "explanation, verification and review gate."
        ),
    ):
        res = call(
            api().post,
            f"/api/invoices/{inv_id}/process",
        )

        if res:
            job = job_progress(
                res["job_id"],
                60,
            )

            if job and job["status"] == "FAILED":
                st.error(
                    f"The workflow failed: {job['error']}. "
                    "The invoice was not approved or paid."
                )

            if job and job["status"] == "SUCCEEDED":
                st.rerun()


# ---------------------------------------------------------
# WORKFLOW STAGES
# ---------------------------------------------------------

st.divider()
st.subheader("Workflow execution")

checkpoints = detail["workflow"]["checkpoints"]

done = {
    checkpoint["node"]: checkpoint
    for checkpoint in checkpoints
}

retries = max(
    [
        checkpoint["retry_count"]
        for checkpoint in checkpoints
    ] or [0]
)

STAGES = [
    ("plan", "Classification & planning"),
    ("vendor", "Vendor verification"),
    ("matching", "Arithmetic, PO / GRN matching and duplicates"),
    ("explain", "Risk explanation (AI or template)"),
    ("verify", "Verification of explanation"),
    ("fallback", "Template fallback (only if needed)"),
    ("save", "Store explanation"),
    ("review_gate", "Hand-off to human review"),
    ("audit", "Audit event"),
]

stage_rows = []

for node, label in STAGES:
    if node in done:
        state = "Completed"
        completed_at = done[node]["at"]
    elif node == "fallback":
        state = "Not required"
        completed_at = None
    else:
        state = "Not run"
        completed_at = None

    stage_rows.append({
        "Workflow stage": label,
        "Execution status": state,
        "Completed at": completed_at,
    })

table(stage_rows)

current_status = status_label(
    detail["invoice"]["status"]
)

st.caption(
    f"Verification retries used: {retries} (limit 2). "
    f"Current invoice status: {current_status}. "
    "Payments can only follow a recorded human approval."
)


# ---------------------------------------------------------
# INTEGRATION STATUS
# ---------------------------------------------------------

integrations = detail["integrations"]

if integrations:
    with st.expander(
        f"Integration activity ({len(integrations)})",
        expanded=False,
    ):
        for integration in integrations:
            st.markdown(
                f"**{integration['integration']}**"
            )

            st.caption(
                f"Status: {integration['status']} | "
                f"Attempts: {integration['attempts']}"
            )


# ---------------------------------------------------------
# INVOICE ANALYSIS WORKSPACE
# ---------------------------------------------------------

st.divider()
st.subheader("Invoice analysis workspace")

st.caption(
    "Review the extracted information, validation results, "
    "risk evidence, AI explanation and original document."
)

tabs = st.tabs([
    "Extraction",
    "Arithmetic & matching",
    "Findings & evidence",
    "Explanation",
    "Original document",
    "Timeline & audit",
])


# ---------------------------------------------------------
# TAB 1: EXTRACTION
# ---------------------------------------------------------

with tabs[0]:
    st.markdown("### Extracted invoice information")

    fields_table(detail)

    st.divider()

    st.markdown("### Invoice line items")

    lines_table(detail)


# ---------------------------------------------------------
# TAB 2: ARITHMETIC AND MATCHING
# ---------------------------------------------------------

with tabs[1]:
    st.markdown("### Validation overview")

    grouped = group_exceptions([
        exception
        for exception in detail["exceptions"]
        if exception["status"] == "OPEN"
    ])

    categories = (
        "Arithmetic",
        "PO / GRN matching",
        "Duplicates",
        "Field validation",
    )

    for category in categories:
        count = len(grouped.get(category, []))

        if count == 0:
            st.success(
                f"{category}: No open findings"
            )
        else:
            st.warning(
                f"{category}: {count} open finding(s)"
            )

    st.divider()

    st.markdown("### Matching findings")

    findings_view(
        detail,
        (
            "Arithmetic",
            "PO / GRN matching",
            "Duplicates",
            "Field validation",
        ),
    )


# ---------------------------------------------------------
# TAB 3: FINDINGS AND EVIDENCE
# ---------------------------------------------------------

with tabs[2]:
    st.markdown("### Risk findings and evidence")

    findings_view(detail)


# ---------------------------------------------------------
# TAB 4: AI EXPLANATION
# ---------------------------------------------------------

with tabs[3]:
    st.markdown("### Risk explanation")

    explanation_panel(detail)


# ---------------------------------------------------------
# TAB 5: ORIGINAL DOCUMENT
# ---------------------------------------------------------

with tabs[4]:
    st.markdown("### Original invoice document")

    document_preview(
        detail["document"]
    )


# ---------------------------------------------------------
# TAB 6: TIMELINE AND AUDIT
# ---------------------------------------------------------

with tabs[5]:
    st.markdown("### Audit and event history")

    if can(u["role"], "view_audit"):

        if st.button(
            "Generate audit summary",
            key="wf_audit_summary",
        ):
            summary = call(
                api().post,
                f"/api/invoices/{inv_id}/audit-summary",
            )

            if summary:
                (
                    st.success
                    if summary["source"] == "model"
                    else st.info
                )(summary["label"])

                st.write(summary["summary"])

                st.markdown(
                    "### Original event timeline"
                )

                st.code(
                    "\n".join(summary["timeline"])
                    or "No events"
                )

        events = call(
            api().get,
            f"/api/invoices/{inv_id}/events",
        )

        if events:
            st.markdown("### Recorded events")

            table([
                {
                    "When": event["created_at"],
                    "Who": event["actor_label"],
                    "Action": event["action"],
                    "Decision": event["decision"],
                }
                for event in events["events"]
            ])

        else:
            st.info(
                "No audit events are currently available."
            )

    else:
        st.caption(
            "Your role cannot view the audit trail."
        )
