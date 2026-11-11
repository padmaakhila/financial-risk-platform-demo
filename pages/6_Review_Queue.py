
import uuid
import html

import streamlit as st

from ui.components import document_preview, explanation_panel, fields_table, findings_view, history_view, lines_table, table
from ui.format import money, severity_label, status_label
from ui.state import api, call, header, require_login

u = require_login("view_queue")

st.markdown("""
<div id="review-queue-style-marker"></div>

<style>
/* Review Queue summary cards */
.rq-metric-card {
    box-sizing: border-box;
    width: 100%;
    min-width: 0;
    min-height: 110px;
    height: 110%;
    padding: 10px;
    background: linear-gradient(145deg, #20243a, #151827);
    border: 1px solid rgba(139, 92, 246, 0.35);
    border-radius: 12px;
    box-shadow:
        0 0 12px rgba(139, 92, 246, 0.12),
        0 8px 22px rgba(0, 0, 0, 0.25);
    transition: all 0.25s ease;
}

.rq-metric-card:hover {
    transform: translateY(-3px);
    border-color: rgba(139, 92, 246, 0.8);
    box-shadow:
        0 0 20px rgba(139, 92, 246, 0.3),
        0 10px 26px rgba(0, 0, 0, 0.3);
}

.rq-metric-label {
    color: #cbd5e1;
    font-size: 14px;
    margin-bottom: 12px;
}

.rq-metric-value {
    color: #f8fafc;
    font-size: 15px;
    font-weight: 400;
    line-height: 1.5;
    white-space: normal;
    overflow-wrap: anywhere;
    word-break: normal;
}
</style>
""", unsafe_allow_html=True)

header(
    "Review & Approval Queue",
    "Cases that need a human decision. Approvals, rejections and payment releases are enforced and audited by the backend."
)

queue = call(api().get, "/api/review/queue")
if queue is None:
    st.stop()

st.subheader(f"Awaiting your decision ({queue['total']})")

items = queue["items"]

if not items:
    st.success("The queue is empty.")

else:
    table([
        {
            "ID": i["id"],
            "Invoice": i["invoice_number"],
            "Vendor": i["vendor"],
            "Total": money(i["grand_total"], i["currency"]),
            "Open findings": i["open_exceptions"],
            "Highest": severity_label(i["highest_severity"]),
            "Explanation": i["explanation_source"] or "—"
        }
        for i in items
    ])

    inv_id = st.selectbox(
        "Open a case",
        [i["id"] for i in items],
        key="rq_pick",
        format_func=lambda x: next(
            f"{i['invoice_number']} · {i['vendor']} · {severity_label(i['highest_severity'])}"
            for i in items if i["id"] == x
        )
    )

    detail = call(api().get, f"/api/invoices/{inv_id}")

    if detail:

        # Five custom summary cards
        selected_item = next(i for i in items if i["id"] == inv_id)

        open_findings_count = sum(
            1 for e in detail["exceptions"] if e["status"] == "OPEN"
        )

        metrics = [
            ("Invoice Number", selected_item["invoice_number"]),
            ("Vendor Name", selected_item["vendor"]),
            ("Invoice Amount", money(selected_item["grand_total"], selected_item["currency"])),
            ("Review Status", status_label(selected_item["status"])),
            ("Open Findings", open_findings_count),
        ]

        cols = st.columns(5)

        for col, (label, value) in zip(cols, metrics):
            with col:
                st.markdown(
                    f"""
                    <div class="rq-metric-card">
                        <div class="rq-metric-label">{html.escape(str(label))}</div>
                        <div class="rq-metric-value">{html.escape(str(value))}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        t = st.tabs([
            "Summary",
            "Findings",
            "Extracted fields & evidence",
            "AI explanation",
            "Original document",
            "Processing history",
            "Decision"
        ])

        with t[0]:
            lines_table(detail)

            ex = [
                e for e in detail["exceptions"]
                if e["status"] == "OPEN"
            ]

            dup = [
                e for e in ex
                if e["rule_id"].startswith("DUP_")
            ]

            if dup:
                st.warning(
                    "Duplicate warning: " +
                    "; ".join(e["message"] for e in dup)
                )

            low = [
                f for f in detail["extracted_fields"]
                if f["confidence"] is not None
                and f["confidence"] < 0.7
            ]

            if low:
                st.warning(
                    f"{len(low)} extracted field(s) have low OCR confidence; check them against the original."
                )

        with t[1]:
            findings_view(detail)

        with t[2]:
            fields_table(detail)

        with t[3]:
            explanation_panel(detail)

        with t[4]:
            document_preview(detail["document"])

        with t[5]:
            history_view(inv_id)

        with t[6]:
            serious = sum(
                1 for e in detail["exceptions"]
                if e["status"] == "OPEN"
                and e["severity"] in ("high", "critical")
            )

            if serious:
                st.warning(
                    f"{serious} high/critical finding(s) are open. Approving requires a written justification."
                )

            key = f"idem_{inv_id}"
            st.session_state.setdefault(key, uuid.uuid4().hex)

            with st.form(f"decision_{inv_id}"):

                decision = st.radio(
                    "Decision",
                    ["approve", "reject", "request_documents"],
                    format_func=lambda x: {
                        "approve": "Approve",
                        "reject": "Reject",
                        "request_documents": "Request more documents"
                    }[x],
                    horizontal=True
                )

                comment = st.text_area(
                    "Comment / justification",
                    max_chars=2000,
                    help="Required for reject and request-documents; also required to approve with open high/critical findings."
                )

                confirm = st.checkbox(
                    "I reviewed the evidence and understand this decision is recorded in the audit trail."
                )

                submitted = st.form_submit_button(
                    "Record decision",
                    type="primary"
                )

            if submitted:
                if not confirm:
                    st.error("Please tick the confirmation box first.")

                else:
                    r = call(
                        api().post,
                        f"/api/invoices/{inv_id}/decision",
                        {
                            "decision": decision,
                            "comment": comment or None,
                            "idempotency_key": st.session_state[key]
                        }
                    )

                    if r:
                        del st.session_state[key]

                        st.success(
                            f"Decision recorded (review #{r['review_id']}). Invoice status is now **{status_label(r['invoice_status'])}**."
                        )

                        st.rerun()


st.divider()

st.subheader("Approved invoices ready for payment")

st.caption(
    "A payment is only possible for an invoice with a recorded approval. If the ERP is down the payment stays pending and can be retried safely."
)

ready = []

for s in ("APPROVED", "PAYMENT_PENDING"):
    r = call(api().get, "/api/invoices", status=s, limit=50)
    ready += r["items"] if r else []

if not ready:
    st.caption("None right now.")

else:
    table([
        {
            "ID": i["id"],
            "Invoice": i["invoice_number"],
            "Vendor": i["vendor"],
            "Total": money(i["grand_total"], i["currency"]),
            "Status": status_label(i["status"])
        }
        for i in ready
    ])

    pay_id = st.selectbox(
        "Invoice to pay",
        [i["id"] for i in ready],
        key="pay_pick",
        format_func=lambda x: next(
            f"{i['invoice_number']} · {money(i['grand_total'], i['currency'])}"
            for i in ready if i["id"] == x
        )
    )

    ok = st.checkbox(
        "I confirm the payment of this invoice to the mock ERP.",
        key="pay_confirm"
    )

    if st.button("Release payment", disabled=not ok):
        r = call(api().post, f"/api/invoices/{pay_id}/payment")

        if r and r["status"] == "PAID":
            st.success(
                f"Payment posted (ERP reference {r['payment_id']})"
                f"{' - this was a safe replay of an earlier request' if r.get('replayed') else ''}."
            )

        elif r:
            st.warning(
                r.get("reason") or "The ERP is unavailable; the payment stays pending."
            )
