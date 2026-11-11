import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from backend.database.session import make_engine
from backend.models import (AuditEvent, Base, Invoice, InvoiceLine, Review, ScenarioGroundTruth, User, Vendor)
from backend.services.audit import append_audit_event, verify_audit_chain
from scripts.generate_data import build_dataset
from scripts.seed_database import seed


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "test.db"
    engine = make_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        summary = seed(s, build_dataset(42))
        s.commit()
    return engine, summary


def test_seed_counts_and_roles(seeded):
    engine, summary = seeded
    with Session(engine) as s:
        assert s.scalar(select(func.count(Invoice.id))) == summary["invoices"] >= 500
        assert s.scalar(select(func.count(InvoiceLine.id))) == summary["invoice_lines"]
        assert s.scalar(select(func.count(ScenarioGroundTruth.id))) == 520 + 10
        assert {u.role for u in s.scalars(select(User))} == {"admin", "reviewer", "ap_clerk", "auditor"}


def test_passwords_never_stored_in_plaintext(seeded):
    engine, _ = seeded
    with Session(engine) as s:
        assert all(u.password_hash.startswith("scrypt$") for u in s.scalars(select(User)))


def test_money_roundtrips_as_exact_decimal(seeded):
    from decimal import Decimal
    engine, _ = seeded
    with Session(engine) as s:
        inv = s.scalars(select(Invoice).where(Invoice.grand_total.is_not(None))).first()
        assert isinstance(inv.grand_total, Decimal)
        assert isinstance(inv.subtotal, Decimal) and inv.grand_total.as_tuple().exponent == -2


def test_foreign_keys_are_enforced(seeded):
    engine, _ = seeded
    with Session(engine) as s:
        s.add(InvoiceLine(invoice_id=99999999, line_no=1, description="x", quantity=1, unit_price=1, line_total=1, tax_amount=0))
        with pytest.raises(IntegrityError):
            s.commit()


def test_check_constraints_and_float_money_rejected(seeded):
    engine, _ = seeded
    with Session(engine) as s:
        s.add(User(username="evil", password_hash="x", role="superuser"))
        with pytest.raises(IntegrityError):
            s.commit()
    with Session(engine) as s:
        v = s.scalars(select(Vendor)).first()
        s.add(Invoice(seq=9999, vendor_id=v.id, grand_total=10.5))
        with pytest.raises((StatementError, TypeError)):
            s.commit()


def test_review_idempotency_key_is_unique(seeded):
    engine, _ = seeded
    with Session(engine) as s:
        inv, user = s.scalars(select(Invoice)).first(), s.scalars(select(User)).first()
        s.add(Review(invoice_id=inv.id, reviewer_id=user.id, decision="approve", idempotency_key="k1"))
        s.commit()
        s.add(Review(invoice_id=inv.id, reviewer_id=user.id, decision="approve", idempotency_key="k1"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_audit_chain_valid_then_detects_tampering(seeded):
    engine, _ = seeded
    with Session(engine) as s:
        assert verify_audit_chain(s) == (True, None)
        ev = append_audit_event(s, actor_id=None, actor_label="test", action="X", entity_type="invoice", entity_id=1,
                                tool_result={"ok": True})
        s.commit()
        assert verify_audit_chain(s) == (True, None)
        s.execute(text("UPDATE audit_events SET action='TAMPERED' WHERE id=:i"), {"i": ev.id})
        s.commit()
        ok, bad_id = verify_audit_chain(s)
        assert ok is False and bad_id == ev.id
        assert s.scalar(select(func.count(AuditEvent.id))) > 520
