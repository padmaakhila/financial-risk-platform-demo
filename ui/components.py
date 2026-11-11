
"""Reusable Streamlit panels shared by several pages."""
from __future__ import annotations

import html
import time

import pandas as pd
import streamlit as st

from ui.format import (
    confidence_label,
    explanation_banner,
    find_source_snippets,
    group_exceptions,
    money,
    severity_label,
    status_label,
)
from ui.preview import pdf_first_page_png, preview_kind
from ui.state import api, call


def metric_card(label, value, help_text=None):
    """Display a responsive metric card with safely escaped content."""

    label_html = html.escape(str(label))
    value_html = html.escape(str(value))

    help_html = ""
    if help_text:
        help_html = (
            '<div class="metric-card-help">'
            f"{html.escape(str(help_text))}"
            "</div>"
        )

    st.markdown(
        f"""
        <div class="custom-metric-card">
            <div class="custom-metric-label">{label_html}</div>
            <div class="custom-metric-value">{value_html}</div>
            {help_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def table(rows: list[dict], **kwargs) -> None:
    """Display a consistent data table or an empty-state message."""

    if rows:
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            **kwargs,
        )
    else:
        st.caption("Nothing to show.")


def invoice_header(detail: dict) -> None:
    """Display the key information for an invoice."""

    inv = detail["invoice"]
    columns = st.columns(5)

    columns[0].metric(
        "Invoice",
        inv["invoice_number"] or "—",
    )
    columns[1].metric(
        "Vendor",
        inv["vendor"] or "—",
    )
    columns[2].metric(
        "Total",
        money(inv["grand_total"], inv["currency"]),
    )
    columns[3].metric(
        "Status",
        status_label(inv["status"]),
    )
    columns[4].metric(
        "Open findings",
        sum(
            1
            for exception in detail["exceptions"]
            if exception["status"] == "OPEN"
        ),
    )

    st.caption(
        f"PO: {inv['po_number'] or '—'}  |  "
        f"GRN: {inv['grn_number'] or '—'}  |  "
        f"Invoice date: {inv['invoice_date'] or '—'}  |  "
        f"Due date: {inv['due_date'] or '—'}"
    )

    st.caption(
        f"Tax ID: {inv['vendor_tax_id'] or '—'}  |  "
        f"Bank: {inv['bank_account'] or '—'}  |  "
        f"Source: {inv['data_source'] or '—'}"
    )


def lines_table(detail: dict) -> None:
    """Display invoice line items and financial totals."""

    table(
        [
            {
                "Line": line["line_no"],
                "Description": line["description"],
                "Quantity": line["quantity"],
                "Unit price": line["unit_price"],
                "Discount %": line["discount_pct"],
                "Tax rate": line["tax_rate"],
                "Line total": line["line_total"],
                "Tax amount": line["tax_amount"],
            }
            for line in detail["lines"]
        ]
    )

    invoice = detail["invoice"]

    st.caption(
        f"Subtotal: {money(invoice['subtotal'], invoice['currency'])}  |  "
        f"Tax: {money(invoice['tax_total'], invoice['currency'])}  |  "
        f"Grand total: {money(invoice['grand_total'], invoice['currency'])}"
    )


def fields_table(detail: dict) -> None:
    """Display extracted document fields and confidence information."""

    fields = detail["extracted_fields"]

    if not fields:
        st.info(
            "No extraction record is available. "
            "This invoice came from the synthetic seed data "
            "rather than an uploaded document."
        )
        return

    table(
        [
            {
                "Field": field["name"],
                "Value": field["value"],
                "Confidence": confidence_label(
                    field["confidence"],
                    field["method"],
                ),
                "Page": field["page"],
                "Source text": field["snippet"],
            }
            for field in fields
        ]
    )


def findings_view(detail: dict, groups: tuple | None = None) -> None:
    """Display open findings grouped by their existing categories."""

    exceptions = [
        exception
        for exception in detail["exceptions"]
        if exception["status"] == "OPEN"
    ]

    if not exceptions:
        st.success(
            "No open findings. Arithmetic, matching and duplicate checks passed."
        )
        return

    grouped = group_exceptions(exceptions)

    for group, items in grouped.items():
        if groups and group not in groups:
            continue

        st.markdown(f"**{group}**")

        table(
            [
                {
                    "Severity": severity_label(exception["severity"]),
                    "Rule": exception["rule_id"],
                    "What was found": exception["message"],
                    "Expected": exception["expected"],
                    "Actual": exception["actual"],
                    "Difference": exception["difference"],
                    "Result": exception["outcome"],
                }
                for exception in items
            ]
        )

        for exception in items:
            with st.expander(
                f"Evidence for {exception['rule_id']} "
                f"(finding #{exception['id']})"
            ):
                snippets = find_source_snippets(
                    exception,
                    detail["extracted_fields"],
                )

                if snippets:
                    for snippet in snippets:
                        st.markdown(
                            f"Source on page "
                            f"**{snippet['page'] or '?'}**: "
                            f"`{snippet['snippet']}` "
                            f"({confidence_label(snippet['confidence'], snippet['method'])})"
                        )
                else:
                    st.caption("No source snippets are available.")

                st.json(
                    exception["evidence"]
                    or {"note": "No additional evidence recorded."}
                )


def explanation_panel(detail: dict) -> None:
    """Display the existing AI risk explanation and verification details."""

    ai = detail["ai"].get("risk_explanation")

    kind, message = explanation_banner(
        ai["source"] if ai else None
    )

    # Custom colours apply only to the AI explanation status banner.
    banner_styles = {
        "success": ("#E8F5EE", "#14532D", "#86C9A0"),
        "warning": ("#FFF7E6", "#854D0E", "#E8C878"),
        "info": ("#E8F1FF", "#1E40AF", "#93B4E8"),
    }

    bg, text_color, border_color = banner_styles.get(
        kind,
        ("#E8F1FF", "#1E40AF", "#93B4E8"),
    )

    st.markdown(
        f"""
        <div style="
            background-color: {bg};
            color: {text_color};
            border: 1px solid {border_color};
            border-radius: 10px;
            padding: 14px 18px;
            font-size: 14px;
            font-weight: 600;
            line-height: 1.5;
        ">
            {html.escape(message)}
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not ai:
        return

    st.write(ai["summary"])

    rule_lookup = {
        exception["id"]: exception["rule_id"]
        for exception in detail["exceptions"]
    }

    table(
        [
            {
                "Finding": (
                    f"#{item['finding_id']} "
                    f"{rule_lookup.get(item['finding_id'], '')}"
                ),
                "Explanation": item["explanation"],
            }
            for item in (ai["items"] or [])
        ]
    )

    for caveat in ai["caveats"] or []:
        st.warning(f"Caveat: {caveat}")

    verification = ai.get("verification") or {}

    if verification.get("fallback_reason"):
        st.caption(
            f"Template used because: "
            f"{verification['fallback_reason']}."
        )

    attempts = verification.get("attempts") or []

    if attempts:
        with st.expander("Model attempts and verification"):
            table(
                [
                    {
                        "Attempt": attempt.get("n"),
                        "Outcome": attempt.get("outcome"),
                        "Problems": "; ".join(
                            attempt.get("problems") or []
                        ),
                    }
                    for attempt in attempts
                ]
            )


def history_view(invoice_id: int) -> None:
    """Display invoice audit history when the user's role permits it."""

    events = call(
        api().get,
        f"/api/invoices/{invoice_id}/events",
        quiet=("FORBIDDEN",),
    )

    if events is None:
        st.caption("Your role cannot view the audit history.")
        return

    table(
        [
            {
                "When": event["created_at"],
                "Who": event["actor_label"],
                "Action": event["action"],
                "Decision": event["decision"],
                "Result": ", ".join(
                    f"{key}={value}"
                    for key, value in (
                        event["tool_result"] or {}
                    ).items()
                    if not isinstance(value, (dict, list))
                )[:120],
            }
            for event in events["events"]
        ]
    )


def document_preview(document: dict | None) -> None:
    """Preview and download the original uploaded document."""

    if not document:
        st.info(
            "No original document is attached. "
            "This is a synthetic seed record."
        )
        return

    result = call(
        api().get_bytes,
        f"/api/documents/{document['id']}/file",
        quiet=("NOT_FOUND",),
    )

    if not result:
        st.caption("The original file is not available to you.")
        return

    data = result[0]
    kind = preview_kind(document["filename"])

    if kind == "pdf":
        png = pdf_first_page_png(data, 90)

        if png:
            st.image(
                png,
                caption=f"{document['filename']} — page 1",
            )
        else:
            st.warning(
                "This PDF could not be rendered for preview."
            )

    elif kind == "image":
        st.image(
            data,
            caption=document["filename"],
        )

    st.download_button(
        "Download original",
        data,
        file_name=document["filename"],
        mime=(
            document.get("mime_type")
            or "application/octet-stream"
        ),
        key=f"dl_{document['id']}",
    )


def job_progress(job_id: str, seconds: int = 45) -> dict | None:
    """Poll a background job and show its latest progress."""

    progress_bar = st.progress(
        0,
        text="Queued",
    )

    job = None
    max_checks = max(1, int(seconds / 1.5))

    for _ in range(max_checks):
        job = call(
            api().get,
            f"/api/jobs/{job_id}",
        )

        if job is None:
            return None

        progress = max(
            0,
            min(100, job["progress_pct"]),
        )

        progress_bar.progress(
            progress / 100,
            text=(
                f"{job['status'].title()} "
                f"({progress}%)"
            ),
        )

        if job["status"] in ("SUCCEEDED", "FAILED"):
            break

        time.sleep(1.5)

    return job
