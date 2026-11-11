"""Reconciliation report: totals are computed in Python from the same rows that are exported, so they always agree."""
from __future__ import annotations

import csv
import io
from decimal import Decimal

COLUMNS = ["invoice_id", "invoice_number", "vendor", "invoice_date", "currency", "grand_total", "status", "exception_count",
           "highest_severity", "latest_decision", "payment_status"]
SEV = ["info", "low", "medium", "high", "critical"]


def build_totals(rows: list[dict]) -> dict:
    by_status: dict = {}
    amount_by_currency: dict = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        if r.get("grand_total") is not None and r.get("currency"):
            amount_by_currency[r["currency"]] = amount_by_currency.get(r["currency"], Decimal("0")) + Decimal(r["grand_total"])
    return {"invoice_count": len(rows), "exception_total": sum(r["exception_count"] for r in rows), "by_status": by_status,
            "amount_by_currency": {k: str(v) for k, v in amount_by_currency.items()},
            "paid_count": sum(1 for r in rows if r["status"] == "PAID")}


def render_csv(rows: list[dict]) -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for r in rows:
        # Spreadsheet formula-injection guard: text cells starting with = + - @ get a leading apostrophe.
        w.writerow({k: ("'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else ("" if v is None else v)) for k, v in r.items()})
    t = build_totals(rows)
    w2 = csv.writer(out, lineterminator="\n")
    w2.writerow([])
    w2.writerow(["TOTALS", "invoices", t["invoice_count"], "exceptions", t["exception_total"], "amounts", "; ".join(f"{c} {a}" for c, a in sorted(t["amount_by_currency"].items()))])
    return out.getvalue()


def render_pdf(rows: list[dict], title: str = "Reconciliation Report", generated: str = "") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), title=title, leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24)
    styles = getSampleStyleSheet()
    t = build_totals(rows)
    story = [Paragraph(title, styles["Title"]), Paragraph(f"Generated {generated}. Synthetic data only.", styles["Normal"]), Spacer(1, 8),
             Paragraph(f"Invoices: {t['invoice_count']} | Exceptions: {t['exception_total']} | Paid: {t['paid_count']} | "
                       f"Amounts: {'; '.join(f'{c} {a}' for c, a in sorted(t['amount_by_currency'].items())) or 'n/a'}", styles["Normal"]), Spacer(1, 8)]
    head = ["Invoice", "Vendor", "Date", "Total", "Status", "Exc.", "Top sev.", "Decision"]
    data = [head] + [[r["invoice_number"] or "-", (r["vendor"] or "-")[:28], r["invoice_date"] or "-", f"{r['currency'] or ''} {r['grand_total'] or ''}".strip(),
                      r["status"], str(r["exception_count"]), r["highest_severity"] or "-", r["latest_decision"] or "-"] for r in rows]
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("FONTSIZE", (0, 0), (-1, -1), 7), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f5f9")])]))
    story.append(table)
    doc.build(story)
    return buf.getvalue()


def fetch_reconciliation_rows(session, status: str | None = None, limit: int = 5000) -> list[dict]:
    from sqlalchemy import select
    from backend.models import ExceptionRecord, Invoice, Review, Vendor
    q = select(Invoice, Vendor.name).join(Vendor, Vendor.id == Invoice.vendor_id, isouter=True).order_by(Invoice.id).limit(limit)
    if status:
        q = q.where(Invoice.status == status)
    exc: dict = {}
    for inv_id, sev in session.execute(select(ExceptionRecord.invoice_id, ExceptionRecord.severity).where(ExceptionRecord.status == "OPEN")):
        exc.setdefault(inv_id, []).append(sev)
    decisions = {}
    for inv_id, decision in session.execute(select(Review.invoice_id, Review.decision).order_by(Review.id)):
        decisions[inv_id] = decision
    rows = []
    for inv, vendor in session.execute(q):
        sevs = exc.get(inv.id, [])
        rows.append({"invoice_id": inv.id, "invoice_number": inv.invoice_number, "vendor": vendor or inv.vendor_name_raw,
                     "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None, "currency": inv.currency,
                     "grand_total": str(inv.grand_total) if inv.grand_total is not None else None, "status": inv.status,
                     "exception_count": len(sevs), "highest_severity": max(sevs, key=SEV.index) if sevs else None,
                     "latest_decision": decisions.get(inv.id), "payment_status": "PAID" if inv.status == "PAID" else ("PENDING" if inv.status == "PAYMENT_PENDING" else "NOT_PAID")})
    return rows
