import streamlit as st

from ui.components import table
from ui.format import money, severity_label, status_label
from ui.state import api, call, header, require_login

require_login("view_reports")
header("Reports", "Reconciliation report. Totals are computed from the same database rows that are exported, so they always agree.")
status = st.selectbox("Filter by status", ["(all)", "RECEIVED", "AWAITING_REVIEW", "NEEDS_MANUAL_ENTRY", "DOCUMENTS_REQUESTED", "APPROVED", "REJECTED", "PAYMENT_PENDING", "PAID", "FAILED"])
flt = None if status == "(all)" else status
rep = call(api().get, "/api/reports/reconciliation", status=flt)
if rep is None:
    st.stop()
t = rep["totals"]
c = st.columns(4)
c[0].metric("Invoices in report", t["invoice_count"])
c[1].metric("Open exceptions", t["exception_total"])
c[2].metric("Paid", t["paid_count"])
c[3].metric("Amount by currency", " · ".join(f"{k} {money(v)}" for k, v in t["amount_by_currency"].items()) or "—")
st.markdown("**By status**: " + ", ".join(f"{status_label(k)}: {v}" for k, v in t["by_status"].items()))
table([{"Invoice": r["invoice_number"], "Vendor": r["vendor"], "Date": r["invoice_date"], "Total": money(r["grand_total"], r["currency"]), "Status": status_label(r["status"]),
        "Exceptions": r["exception_count"], "Highest": severity_label(r["highest_severity"]), "Decision": r["latest_decision"], "Payment": r["payment_status"]} for r in rep["rows"]])

st.subheader("Download")
st.caption("Each export is recorded in the audit trail.")
c1, c2 = st.columns(2)
for col, kind, mime in ((c1, "csv", "text/csv"), (c2, "pdf", "application/pdf")):
    with col:
        key = f"export_{kind}_{flt}"
        if st.button(f"Prepare {kind.upper()} export", key=f"prep_{key}"):
            got = call(api().get_bytes, f"/api/reports/reconciliation.{kind}", status=flt)
            if got:
                st.session_state[key] = (got[0], got[2] or f"reconciliation.{kind}")
        if key in st.session_state:
            data, name = st.session_state[key]
            st.download_button(f"Download {name}", data, file_name=name, mime=mime, key=f"dl_{key}")
