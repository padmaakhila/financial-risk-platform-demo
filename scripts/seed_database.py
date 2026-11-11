"""Load the synthetic dataset (vendors, POs, GRNs, invoices, ground truth, demo users).
Run from the project root:  python -m scripts.seed_database [--seed 42]
Refuses to run when APP_ENV=production.
"""
from __future__ import annotations

import argparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.security import hash_password
from backend.models import (GoodsReceipt, GoodsReceiptLine, Invoice, InvoiceLine, PurchaseOrder, PurchaseOrderLine,
                            ScenarioGroundTruth, User, Vendor)
from backend.services.audit import append_audit_event
from scripts.generate_data import build_dataset, summarize
from scripts.init_db import init_db


def seed(session: Session, dataset: dict) -> dict:
    if session.scalar(select(func.count(Invoice.id))):
        raise RuntimeError("Database already contains invoices. Run scripts.reset_database first.")
    users = {}
    for username, role, password in dataset["users"]:
        u = User(username=username, role=role, password_hash=hash_password(password))
        session.add(u)
        users[username] = u
    vendors = {}
    for v in dataset["vendors"]:
        row = Vendor(vendor_code=v["vendor_code"], name=v["name"], tax_id=v["tax_id"], bank_account=v["bank_account"],
                     bank_name=v["bank_name"], verification_status=v["verification_status"], active=v["active"])
        session.add(row)
        vendors[v["vendor_code"]] = row
    session.flush()

    pos = {}
    for p in dataset["purchase_orders"]:
        row = PurchaseOrder(po_number=p["po_number"], vendor_id=vendors[p["vendor_code"]].id, order_date=p["order_date"],
                            currency=p["currency"], status=p["status"],
                            lines=[PurchaseOrderLine(**ln) for ln in p["lines"]])
        session.add(row)
        pos[p["po_number"]] = row
    session.flush()
    for g in dataset["goods_receipts"]:
        session.add(GoodsReceipt(grn_number=g["grn_number"], po_id=pos[g["po_number"]].id, receipt_date=g["receipt_date"],
                                 lines=[GoodsReceiptLine(**ln) for ln in g["lines"]]))

    inv_rows = {}
    for i in dataset["invoices"]:
        data = {k: v for k, v in i.items() if k not in ("lines", "vendor_code", "scenario_code")}
        row = Invoice(**data, vendor_id=vendors[i["vendor_code"]].id, status="RECEIVED", data_source="synthetic",
                      lines=[InvoiceLine(**ln) for ln in i["lines"]])
        session.add(row)
        inv_rows[i["seq"]] = row
    session.flush()

    for t in dataset["ground_truth"]:
        inv = inv_rows.get(t["invoice_seq"]) if t["invoice_seq"] else None
        session.add(ScenarioGroundTruth(scenario_code=t["scenario_code"], invoice_id=inv.id if inv else None,
                                        file_name=t.get("file_name"), expected=_jsonable(t["expected"])))
    for seq, row in inv_rows.items():
        append_audit_event(session, actor_id=None, actor_label="system:seed", action="INVOICE_RECEIVED",
                           entity_type="invoice", entity_id=row.id,
                           details={"invoice_number": row.invoice_number, "source": "synthetic seed"})
    append_audit_event(session, actor_id=None, actor_label="system:seed", action="SEED_COMPLETED", entity_type="system",
                       entity_id="seed", details=summarize(dataset) | {"scenarios": None})
    return summarize(dataset)


def _jsonable(obj):
    import json
    return json.loads(json.dumps(obj, default=str))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-users", action="store_true", help="do not create the demo logins (use scripts.create_admin instead)")
    args = ap.parse_args()
    if get_settings().is_production:
        raise SystemExit("Refusing to seed demo data when APP_ENV=production.")
    init_db()
    from backend.database.session import session_scope
    with session_scope() as s:
        data = build_dataset(args.seed)
        if args.no_users:
            data["users"] = []
        summary = seed(s, data)
    print("Seeded:", {k: v for k, v in summary.items() if k != "scenarios"})
    if args.no_users:
        print("No demo users were created. Create an administrator with: python -m scripts.create_admin")
        return
    print("Demo logins (synthetic, development only):")
    from scripts.generate_data import DEMO_USERS
    for username, role, password in DEMO_USERS:
        print(f"  {username:9s} role={role:9s} password={password}")


if __name__ == "__main__":
    main()
