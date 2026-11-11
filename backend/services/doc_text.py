"""Plain-text layouts of synthetic documents. Used to render PDFs, to train the classifier,
and as the format the rule-based parsers read. One place so they never drift apart."""
from __future__ import annotations


def invoice_lines_text(inv: dict) -> list[str]:
    out = [f"INVOICE {inv['invoice_number']}", f"Vendor: {inv['vendor_name_raw']}", f"Tax ID: {inv['vendor_tax_id_raw']}",
           f"Bank: {inv['bank_account_raw']}", f"Invoice date: {inv['invoice_date'] or ''}", f"Due date: {inv['due_date'] or ''}",
           f"PO: {inv['po_number'] or ''}   GRN: {inv['grn_number'] or ''}", f"Currency: {inv['currency'] or ''}", "",
           "No  Description                      Qty   Unit    Disc%  Tax%   Total   Tax"]
    for ln in inv["lines"]:
        out.append(f"{ln['line_no']:<3} {ln['description'][:60]}  {ln['quantity']}  {ln['unit_price']}  "
                   f"{ln['discount_pct']}  {ln['tax_rate'] * 100:.0f}  {ln['line_total']}  {ln['tax_amount']}")
    out += ["", f"Subtotal: {inv['subtotal']}", f"Tax total: {inv['tax_total']}", f"Grand total: {inv['grand_total']}"]
    if inv.get("notes"):
        out += ["", f"Notes: {inv['notes']}"]
    return out


def po_lines_text(po: dict) -> list[str]:
    out = [f"PURCHASE ORDER {po['po_number']}", f"Vendor code: {po['vendor_code']}", f"Order date: {po['order_date']}",
           f"Currency: {po['currency']}", "", "No  Description                      Qty   Unit price  Tax%"]
    out += [f"{l['line_no']:<3} {l['description'][:60]}  {l['quantity']}  {l['unit_price']}  {l['tax_rate'] * 100:.0f}" for l in po["lines"]]
    return out


def grn_lines_text(grn: dict) -> list[str]:
    out = [f"GOODS RECEIVED NOTE {grn['grn_number']}", f"PO reference: {grn['po_number']}", f"Receipt date: {grn['receipt_date']}",
           "", "No  Description                      Qty received"]
    out += [f"{l['po_line_no']:<3} {l['description'][:60]}  {l['quantity_received']}" for l in grn["lines"]]
    return out


def vendor_lines_text(v: dict) -> list[str]:
    return ["VENDOR MASTER RECORD", f"Vendor code: {v['vendor_code']}", f"Vendor name: {v['name']}", f"Tax ID: {v['tax_id']}",
            f"Bank account: {v['bank_account']}", f"Bank name: {v['bank_name']}", f"Verification status: {v['verification_status']}"]
