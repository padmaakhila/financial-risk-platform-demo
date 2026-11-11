"""Read-only SQLAlchemy repository over the platform's EXISTING models.

Only SELECT statements are issued, always with a LIMIT. Nothing is added,
changed or deleted, and no raw SQL is built from user text (all values are
bound parameters). Columns that are not listed in the project description
(line columns, checkpoint columns, document owner column) are read through
``_pick`` which only copies attributes that actually exist on the model.

Items to verify against your models (see README, "Assumptions"):
  * owner column on ``Document`` used for the AP-clerk ownership rule
  * line / checkpoint column names (copied only if present)
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import String, and_, cast, func, or_, select

from .pii import mask_value

_OWNER_ATTRS = ("uploaded_by", "uploaded_by_id", "uploader_id", "owner_id", "created_by", "created_by_id", "user_id")
_PO_LINE = ("line_no", "line_number", "description", "item_code", "sku", "quantity", "qty", "unit_price", "line_total", "amount")
_GRN_LINE = ("line_no", "line_number", "description", "item_code", "sku", "quantity", "qty", "quantity_received")
_CHECKPOINT = ("step", "stage", "name", "node", "status", "created_at", "updated_at")


def _plain(v: Any) -> Any:
    if v is None or isinstance(v, (int, bool, str)):
        return v
    if isinstance(v, Decimal):
        return str(v)                       # money stays exact text, never float
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)


def _pick(obj: Any, names: Iterable[str]) -> Dict[str, Any]:
    return {n: _plain(getattr(obj, n)) for n in names if hasattr(obj, n)}


def _upper_in(col, values: List[str]):
    return func.upper(col).in_([str(v).upper() for v in values])


class OrmRepo:
    def __init__(self, db, user_id: Any, role: str):
        from backend.models import entities as m
        self.db, self.m, self.user_id, self.role = db, m, user_id, role

    def _all(self, stmt) -> List[Any]:
        return list(self.db.execute(stmt).scalars().all())

    # ---- invoices
    def find_invoices(self, identifiers, vendor_ids, status_terms, limit):
        I = self.m.Invoice
        ident = []
        if identifiers:
            ident += [_upper_in(I.invoice_number, identifiers), _upper_in(I.po_number, identifiers),
                      _upper_in(I.grn_number, identifiers)]
        if vendor_ids:
            ident.append(I.vendor_id.in_(vendor_ids))
        conds = []
        if ident:
            conds.append(or_(*ident))
        if status_terms:
            conds.append(or_(*[I.status.ilike("%" + t + "%") for t in status_terms]))
        if not conds:
            return []
        rows = self._all(select(I).where(and_(*conds)).order_by(I.id.desc()).limit(limit))
        keys = ("id", "invoice_number", "vendor_id", "vendor_name_raw", "vendor_tax_id_raw", "invoice_date", "due_date",
                "po_number", "grn_number", "currency", "subtotal", "tax_total", "grand_total", "notes", "status",
                "document_kind", "document_id", "data_source", "created_at")
        out = []
        for r in rows:
            d = _pick(r, keys)
            d["bank_account_raw"] = mask_value(getattr(r, "bank_account_raw", None))   # masked at the data boundary
            out.append(d)
        return out

    # ---- vendors
    def find_vendors(self, codes, names, ids, limit, include_bank):
        V = self.m.Vendor
        conds = []
        if codes:
            conds.append(_upper_in(V.vendor_code, codes))
        if ids:
            conds.append(V.id.in_(ids))
        for n in names or []:
            conds.append(V.name.ilike("%" + n.replace("%", "").replace("_", "") + "%"))
        if not conds:
            return []
        out = []
        for r in self._all(select(V).where(or_(*conds)).order_by(V.id).limit(limit)):
            d = _pick(r, ("id", "vendor_code", "name", "tax_id", "verification_status", "active"))
            d["bank_account"] = mask_value(r.bank_account) if include_bank else None
            out.append(d)
        return out

    # ---- PO / GRN
    def find_pos(self, numbers, limit):
        P = self.m.PurchaseOrder
        out = []
        for r in self._all(select(P).where(_upper_in(P.po_number, numbers)).order_by(P.id).limit(limit)):
            d = _pick(r, ("id", "po_number", "vendor_id", "order_date", "currency", "status"))
            d["lines"] = [_pick(l, _PO_LINE) for l in list(getattr(r, "lines", []) or [])[:10]]
            out.append(d)
        return out

    def find_grns(self, numbers, limit):
        G, P = self.m.GoodsReceipt, self.m.PurchaseOrder
        out = []
        for r in self._all(select(G).where(_upper_in(G.grn_number, numbers)).order_by(G.id).limit(limit)):
            d = _pick(r, ("id", "grn_number", "po_id", "receipt_date"))
            po = self.db.get(P, r.po_id) if getattr(r, "po_id", None) is not None else None
            d["po_number"] = po.po_number if po is not None else None
            d["lines"] = [_pick(l, _GRN_LINE) for l in list(getattr(r, "lines", []) or [])[:10]]
            out.append(d)
        return out

    # ---- extraction (snippet column only selected when allowed)
    def extracted_fields(self, invoice_id, with_snippets, limit):
        F = self.m.ExtractedField
        cols = [F.field_name, F.value_text, F.confidence, F.confidence_method, F.page_number]
        if with_snippets:
            cols.append(F.source_snippet)
        rows = self.db.execute(select(*cols).where(F.invoice_id == invoice_id).order_by(F.id).limit(limit)).all()
        return [{**{k: _plain(v) for k, v in zip(("field_name", "value_text", "confidence", "confidence_method", "page_number"), r[:5])},
                 **({"source_snippet": r[5]} if with_snippets else {})} for r in rows]

    def document_visible(self, document_id) -> Optional[bool]:
        """AP-clerk ownership rule. Returns None (=> treated as not visible)
        when the owner column cannot be determined."""
        D = self.m.Document
        attr = next((a for a in _OWNER_ATTRS if hasattr(D, a)), None)
        if attr is None:
            return None
        row = self.db.execute(select(getattr(D, attr)).where(D.id == document_id)).first()
        return bool(row is not None and row[0] == self.user_id)

    # ---- findings / workflow / history
    def exceptions(self, invoice_id, limit):
        E = self.m.ExceptionRecord
        rows = self._all(select(E).where(E.invoice_id == invoice_id).order_by(E.id).limit(limit))
        return [_pick(r, ("exception_type", "severity", "rule_id", "expected_value", "actual_value", "difference",
                          "source_evidence", "status", "created_at")) for r in rows]

    def open_high_risk(self, limit):
        E, I = self.m.ExceptionRecord, self.m.Invoice
        stmt = (select(I.invoice_number, E.exception_type, E.severity, E.rule_id, E.status)
                .join(I, I.id == E.invoice_id).where(func.lower(E.severity).in_(["high", "critical"]))
                .order_by(E.id.desc()).limit(limit))
        return [dict(zip(("invoice_number", "exception_type", "severity", "rule_id", "status"), r))
                for r in self.db.execute(stmt).all()]

    def reviews(self, invoice_id, limit):
        R = self.m.Review
        return [_pick(r, ("decision", "comment", "created_at"))
                for r in self._all(select(R).where(R.invoice_id == invoice_id).order_by(R.id.desc()).limit(limit))]

    def checkpoints(self, invoice_id, limit):
        C = self.m.WorkflowCheckpoint
        if not hasattr(C, "invoice_id"):
            return []
        return [_pick(r, _CHECKPOINT)
                for r in self._all(select(C).where(C.invoice_id == invoice_id).order_by(C.id.desc()).limit(limit))]

    def audit_events(self, invoice_id, limit):
        A = self.m.AuditEvent       # only non-sensitive columns; never tool_result/details/hashes
        stmt = (select(A.action, A.actor_label, A.decision, A.created_at)
                .where(and_(func.lower(A.entity_type) == "invoice", cast(A.entity_id, String) == str(invoice_id)))
                .order_by(A.id.desc()).limit(limit))
        return [{"action": r[0], "actor_label": r[1], "decision": r[2], "created_at": _plain(r[3])}
                for r in self.db.execute(stmt).all()]

    def report_counts(self):
        I, E = self.m.Invoice, self.m.ExceptionRecord
        by_status = dict(self.db.execute(select(I.status, func.count()).group_by(I.status).limit(50)).all())
        by_sev = dict(self.db.execute(select(E.severity, func.count()).group_by(E.severity).limit(50)).all())
        return {"invoices_by_status": {str(k): int(v) for k, v in by_status.items()},
                "exceptions_by_severity": {str(k): int(v) for k, v in by_sev.items()}}
