import streamlit as st

from ui.components import document_preview, explanation_panel, fields_table, findings_view, history_view, invoice_header, lines_table, table
from ui.format import money, status_label
from ui.state import api, call, header, require_login

u = require_login("view_records")
st.markdown("""
<style>
/* Business Records invoice summary cards */
div[data-testid="stMetric"] {
    min-width: 0 !important;
    height: 110px !important;
    padding: 10px !important;
    box-sizing: border-box !important;
}

div[data-testid="stMetricValue"] {
    font-size: 15px !important;
    font-weight: 400 !important;
    line-height: 1.4 !important;
    white-space: normal !important;
    overflow-wrap: anywhere !important;
    word-break: normal !important;
    overflow: visible !important;
    text-overflow: clip !important;
}

div[data-testid="stMetricValue"] > div {
    white-space: normal !important;
    overflow-wrap: anywhere !important;
    word-break: normal !important;
    max-width: 100% !important;
}

div[data-testid="stMetricLabel"] {
    font-size: 13px !important;
    font-weight: 400 !important;
    white-space: normal !important;
}
</style>
""", unsafe_allow_html=True)
header("Business Records", "Search, filter and inspect vendors, purchase orders, goods receipts and invoices.")
PAGE = 25
tab_inv, tab_vendor, tab_po, tab_grn = st.tabs(["Invoices", "Vendors", "Purchase orders", "Goods receipts"])


def pager(key: str, total: int) -> int:
    pages = max(1, -(-total // PAGE))
    return st.number_input("Page", min_value=1, max_value=pages, value=1, key=f"page_{key}", help=f"{total} records, {PAGE} per page") - 1


with tab_inv:
    c1, c2 = st.columns([2, 1])
    q = c1.text_input("Search (invoice number, vendor name or PO)", key="inv_q")
    status = c2.selectbox("Status", ["(any)", "RECEIVED", "PROCESSING", "NEEDS_MANUAL_ENTRY", "AWAITING_REVIEW", "DOCUMENTS_REQUESTED", "APPROVED", "REJECTED",
                                     "PAYMENT_PENDING", "PAID", "FAILED"], key="inv_status")
    first = call(api().get, "/api/invoices", q=q or None, status=None if status == "(any)" else status, limit=1)
    if first is not None:
        page = pager("inv", first["total"])
        res = call(api().get, "/api/invoices", q=q or None, status=None if status == "(any)" else status, limit=PAGE, offset=page * PAGE)
        items = res["items"] if res else []
        table([{"ID": i["id"], "Invoice": i["invoice_number"], "Vendor": i["vendor"], "Date": i["invoice_date"], "PO": i["po_number"], "Total": money(i["grand_total"], i["currency"]),
                "Status": status_label(i["status"])} for i in items])
        if items:
            pick = st.selectbox("Inspect an invoice", [i["id"] for i in items], format_func=lambda x: next(f"{i['invoice_number']} · {i['vendor']}" for i in items if i["id"] == x), key="inv_pick")
            detail = call(api().get, f"/api/invoices/{pick}")
            if detail:
                invoice_header(detail)
                t = st.tabs(["Line items", "Findings", "Extracted fields", "Explanation", "Original document", "History"])
                with t[0]:
                    lines_table(detail)
                with t[1]:
                    findings_view(detail)
                with t[2]:
                    fields_table(detail)
                with t[3]:
                    explanation_panel(detail)
                with t[4]:
                    document_preview(detail["document"])
                with t[5]:
                    history_view(pick)

with tab_vendor:
    q = st.text_input("Search vendors (name or code)", key="ven_q")
    first = call(api().get, "/api/vendors", q=q or None, limit=1)
    if first is not None:
        page = pager("ven", first["total"])
        res = call(api().get, "/api/vendors", q=q or None, limit=PAGE, offset=page * PAGE)
        table([{"Code": v["vendor_code"], "Name": v["name"], "Tax ID": v["tax_id"], "Bank": v["bank_name"], "Account": v["bank_account"], "Verification": v["verification_status"],
                "Active": v["active"]} for v in (res["items"] if res else [])])
        if u["role"] not in ("admin", "reviewer"):
            st.caption("Bank account numbers are masked for your role.")

with tab_po:
    q = st.text_input("Search PO number", key="po_q")
    first = call(api().get, "/api/purchase-orders", q=q or None, limit=1)
    if first is not None:
        page = pager("po", first["total"])
        res = call(api().get, "/api/purchase-orders", q=q or None, limit=PAGE, offset=page * PAGE)
        items = res["items"] if res else []
        table([{"PO": p["po_number"], "Vendor": p["vendor"], "Date": p["order_date"], "Currency": p["currency"], "Lines": p["line_count"], "Status": p["status"]} for p in items])
        if items:
            pick = st.selectbox("Inspect a purchase order", [p["po_number"] for p in items], key="po_pick")
            po = call(api().get, f"/api/purchase-orders/{pick}")
            if po:
                st.caption(f"Goods receipts: {', '.join(po['goods_receipts']) or 'none'} · Invoices: {', '.join(po['invoices']) or 'none'}")
                table(po["lines"])

with tab_grn:
    q = st.text_input("Search GRN number", key="grn_q")
    first = call(api().get, "/api/goods-receipts", q=q or None, limit=1)
    if first is not None:
        page = pager("grn", first["total"])
        res = call(api().get, "/api/goods-receipts", q=q or None, limit=PAGE, offset=page * PAGE)
        items = res["items"] if res else []
        table([{"GRN": g["grn_number"], "PO": g["po_number"], "Receipt date": g["receipt_date"], "Lines received": ", ".join(f"{l['po_line_no']}:{l['quantity_received']}" for l in g["lines"])} for g in items])
