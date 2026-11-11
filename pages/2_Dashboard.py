
import pandas as pd
import plotly.express as px
import streamlit as st

from ui.components import table
from ui.format import human_seconds, percent, status_label
from ui.state import api, call, header, require_login


# ---------------------------------------------------------
# PAGE ACCESS AND DATA
# ---------------------------------------------------------

require_login("view_reports")

header(
    "Dashboard",
    "A clear overview of invoice processing, risk exceptions, "
    "workflow performance and AI usage."
)

d = call(api().get, "/api/reports/summary")

if d is None:
    st.stop()


# ---------------------------------------------------------
# DASHBOARD CHART THEME
# ---------------------------------------------------------

CHART_COLORS = [
    "#8B5CF6",
    "#EC4899",
    "#38BDF8",
    "#34D399",
    "#F59E0B",
]

CHART_LAYOUT = {
    "height": 340,
    "margin": dict(l=20, r=20, t=55, b=25),
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "font": {
        "color": "#DCE5F2",
        "family": "Inter, sans-serif",
        "size": 12,
    },
    "title": {
        "font": {
            "size": 16,
            "color": "#F8FAFC",
        },
        "x": 0.02,
        "xanchor": "left",
    },
    "legend": {
        "font": {"color": "#DCE5F2"},
        "bgcolor": "rgba(0,0,0,0)",
    },
    "hoverlabel": {
        "bgcolor": "#172238",
        "font": {"color": "#FFFFFF"},
        "bordercolor": "#64748B",
    },
}


def apply_chart_layout(fig):
    """Apply consistent styling to all dashboard charts."""

    fig.update_layout(**CHART_LAYOUT)

    fig.update_xaxes(
        showgrid=False,
        zeroline=False,
        color="#AAB8CC",
    )

    fig.update_yaxes(
        showgrid=True,
        gridcolor="rgba(148,163,184,0.12)",
        zeroline=False,
        color="#AAB8CC",
    )

    return fig


def show_bar_chart(
    title,
    data,
    label,
    color="#8B5CF6",
    horizontal=False,
    order=None,
):
    """Render a bar chart using database-provided values."""

    if not data:
        st.info(f"No data available for {title.lower()}.")
        return

    df = pd.DataFrame({
        label: list(data.keys()),
        "Count": list(data.values()),
    })

    if order:
        categories = [
            item for item in order
            if item in data
        ]

        df[label] = pd.Categorical(
            df[label],
            categories=categories,
            ordered=True,
        )

        df = df.sort_values(label)

    if horizontal:
        fig = px.bar(
            df,
            x="Count",
            y=label,
            orientation="h",
            title=title,
            color_discrete_sequence=[color],
            text="Count",
        )
    else:
        fig = px.bar(
            df,
            x=label,
            y="Count",
            title=title,
            color_discrete_sequence=[color],
            text="Count",
        )

    fig.update_traces(
        marker_line_width=0,
        textposition="outside",
        cliponaxis=False,
        hovertemplate=(
            "%{y}: %{x}<extra></extra>"
            if horizontal
            else "%{x}: %{y}<extra></extra>"
        ),
    )

    fig = apply_chart_layout(fig)

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displayModeBar": False},
    )


# ---------------------------------------------------------
# SECTION 1: INVOICE OVERVIEW
# ---------------------------------------------------------

st.subheader("Invoice overview")

c = st.columns(5)

c[0].metric(
    "Documents uploaded",
    d["documents_uploaded"],
)

c[1].metric(
    "Total invoices",
    d["invoices_total"],
)

c[2].metric(
    "Pending reviews",
    d["pending_reviews"],
)

c[3].metric(
    "Suspected duplicates",
    d["suspected_duplicates"],
)

c[4].metric(
    "Open exceptions",
    d["open_exceptions"],
)


# ---------------------------------------------------------
# SECTION 2: WORKFLOW PERFORMANCE
# ---------------------------------------------------------

st.subheader("Workflow performance")

j = d["jobs"]

c = st.columns(5)

c[0].metric(
    "Jobs succeeded",
    j["succeeded"],
)

c[1].metric(
    "Jobs failed",
    j["failed"],
)

c[2].metric(
    "Failure rate",
    percent(j["failure_rate"]),
)

c[3].metric(
    "Latency p50",
    human_seconds(j["latency_p50_s"]),
)

c[4].metric(
    "Latency p95",
    human_seconds(j["latency_p95_s"]),
)


st.divider()


# ---------------------------------------------------------
# SECTION 3: INVOICE STATUS AND EXCEPTION SEVERITY
# ---------------------------------------------------------

st.subheader("Risk and processing analytics")

left, right = st.columns(2, gap="large")


# Invoice status bar chart
with left:
    invoice_status = {
        status_label(key): value
        for key, value in d["invoices_by_status"].items()
    }

    show_bar_chart(
        "Invoices by status",
        invoice_status,
        "Status",
        color="#8B5CF6",
    )


# Exception severity donut chart
with right:
    severity_data = d["exceptions_by_severity"]

    if severity_data:
        severity_df = pd.DataFrame({
            "Severity": list(severity_data.keys()),
            "Count": list(severity_data.values()),
        })

        fig = px.pie(
            severity_df,
            names="Severity",
            values="Count",
            hole=0.62,
            title="Exceptions by severity",
            color="Severity",
            color_discrete_map={
                "critical": "#EF4444",
                "high": "#F97316",
                "medium": "#F59E0B",
                "low": "#38BDF8",
                "info": "#8B5CF6",
            },
        )

        fig.update_traces(
            textposition="inside",
            textinfo="percent+label",
            marker=dict(
                line=dict(
                    color="#10182B",
                    width=3,
                )
            ),
            hovertemplate=(
                "%{label}: %{value} (%{percent})"
                "<extra></extra>"
            ),
        )

        fig = apply_chart_layout(fig)

        fig.update_layout(
            showlegend=True,
            legend=dict(
                orientation="h",
                y=-0.12,
                x=0.5,
                xanchor="center",
            ),
        )

        st.plotly_chart(
            fig,
            use_container_width=True,
            config={"displayModeBar": False},
        )

    else:
        st.info("No exception severity data available.")


# ---------------------------------------------------------
# SECTION 4: PENDING INVOICE AGING
# ---------------------------------------------------------

st.subheader("Pending invoice aging")

aging_data = d["aging_pending_days_since_invoice_date"]

if aging_data:
    aging_df = pd.DataFrame({
        "Age": list(aging_data.keys()),
        "Pending invoices": list(aging_data.values()),
    })

    fig = px.area(
        aging_df,
        x="Age",
        y="Pending invoices",
        title="Pending cases by invoice age",
        markers=True,
        color_discrete_sequence=["#38BDF8"],
    )

    fig.update_traces(
        fill="tozeroy",
        line=dict(width=3),
        marker=dict(size=8),
        hovertemplate=(
            "Age: %{x}<br>"
            "Pending invoices: %{y}"
            "<extra></extra>"
        ),
    )

    fig = apply_chart_layout(fig)

    fig.update_layout(
        height=320,
        xaxis_title="Days since invoice date",
        yaxis_title="Pending invoices",
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displayModeBar": False},
    )

else:
    st.info("No pending invoice aging data available.")


# ---------------------------------------------------------
# SECTION 5: EXCEPTION TYPE BREAKDOWN
# ---------------------------------------------------------

with st.expander("View exception type breakdown"):
    show_bar_chart(
        "Exceptions by type",
        d["exceptions_by_type"],
        "Type",
        color="#A78BFA",
        horizontal=True,
    )


# ---------------------------------------------------------
# SECTION 6: AI USAGE
# ---------------------------------------------------------

st.divider()

st.subheader("AI usage and cost")

ai = d["ai"]

c = st.columns(4)

c[0].metric(
    "Model calls",
    ai["model_calls"],
)

c[1].metric(
    "Template fallbacks",
    ai["template_fallbacks"],
    help=(
        "Explanations written by deterministic templates "
        "because the model was unavailable, too slow, "
        "or failed verification."
    ),
)

c[2].metric(
    "Tokens (prompt / answer)",
    f"{ai['prompt_tokens']} / {ai['completion_tokens']}",
)

c[3].metric(
    "Cost (USD)",
    ai["cost_usd"] or "not reported",
    help=(
        ai["cost_note"]
        or "Reported only when the provider returns a cost."
    ),
)


# ---------------------------------------------------------
# SECTION 7: FALLBACK REASONS
# ---------------------------------------------------------

if ai["fallback_reasons"]:
    with st.expander("View AI fallback reasons"):
        fallback_data = [
            {
                "Fallback reason": key,
                "Count": value,
            }
            for key, value in ai["fallback_reasons"].items()
        ]

        table(fallback_data)
else:
    st.caption("No AI template fallbacks have been reported.")
