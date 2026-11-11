"""Needs SQLAlchemy (installed via requirements.txt).
Covers the critical authorization / approval / integrity gates.
"""
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import sessionmaker

from backend.database.session import make_engine
from backend.integrations.clients import ErpClient
from backend.integrations.erp_mock_core import ErpMock
from backend.integrations.mock_server import start_in_thread
from backend.models import (
    AuditEvent,
    Base,
    ExceptionRecord,
    IntegrationRecord,
    Invoice,
    Review,
    User,
)
from backend.services.audit import verify_audit_chain
from backend.services.payments import (
    ApprovalRequired,
    PaymentError,
    pay_invoice,
)
from backend.services.review import (
    Conflict,
    InvalidState,
    PermissionDenied,
    ValidationFailed,
    record_decision,
)
from scripts.generate_data import build_dataset
from scripts.seed_database import seed


DS = build_dataset(42)
CLEAN = [
    invoice["invoice_number"]
    for invoice in DS["invoices"]
    if invoice["scenario_code"] == "S01_CLEAN"
]


import os
from dotenv import load_dotenv

load_dotenv()

@pytest.fixture(scope="module")
def factory():
    test_db_url = os.getenv("TEST_POSTGRES_URL")
    if not test_db_url:
        raise RuntimeError("TEST_POSTGRES_URL is missing from .env")

    engine = make_engine(test_db_url)
    Base.metadata.create_all(engine)

    f = sessionmaker(bind=engine, expire_on_commit=False)


    # Seed the test database and explicitly commit the transaction.
    with f() as s:
        seed(s, DS)
        s.commit()

    yield f
    engine.dispose()


class Env:
    def __init__(self, factory):
        self.f = factory

        with self.f() as s:
            self.uid = {
                user.username: (user.id, user.role)
                for user in s.scalars(select(User))
            }

        self._next = 0

    def invoice(self, status="AWAITING_REVIEW"):
        # Use zero-based indexing so the first call selects CLEAN[0].
        number = CLEAN[self._next]
        self._next += 1

        with self.f() as s:
            inv = s.scalar(
                select(Invoice).where(
                    Invoice.invoice_number == number,
                    Invoice.status == "RECEIVED",
                )
            )

            if inv is None:
                raise AssertionError(
                    f"Test invoice {number!r} not found with status RECEIVED"
                )

            inv.status = status
            s.commit()
            return inv.id

    def decide(
        self,
        inv_id,
        who="reviewer",
        decision="approve",
        comment="looks fine to me",
        key=None,
    ):
        uid, role = self.uid[who]

        with self.f() as s:
            result = record_decision(
                s,
                invoice_id=inv_id,
                reviewer_id=uid,
                reviewer_role=role,
                decision=decision,
                comment=comment,
                idempotency_key=key or f"k-{inv_id}-{decision}-{who}",
            )
            s.commit()
            return result

    def status(self, inv_id):
        with self.f() as s:
            return s.get(Invoice, inv_id).status

    def pay(self, client, inv_id, who="reviewer"):
        uid, role = self.uid[who]

        return pay_invoice(
            self.f,
            client,
            invoice_id=inv_id,
            actor_id=uid,
            actor_role=role,
        )

    def count(self, model, *where):
        with self.f() as s:
            return s.scalar(
                select(func.count())
                .select_from(model)
                .where(*where)
            )


@pytest.fixture
def env(factory):
    return Env(factory)


@pytest.fixture
def erp():
    core = ErpMock(timeout_delay=1.0)
    srv, url = start_in_thread(core)

    yield core, ErpClient(url, timeout=0.5, sleep=lambda s: None)

    srv.shutdown()


# ---------------------------------------------------------------- authorization


def test_only_reviewers_and_admins_can_decide(env):
    inv = env.invoice()

    for who in ("clerk", "auditor"):
        with pytest.raises(PermissionDenied):
            env.decide(inv, who)

    assert (
        env.status(inv) == "AWAITING_REVIEW"
        and env.count(Review, Review.invoice_id == inv) == 0
    )


def test_approve_records_review_status_and_audit_event(env):
    inv = env.invoice()
    r = env.decide(inv, "reviewer", "approve")

    assert r.decision == "approve"
    assert env.status(inv) == "APPROVED"

    with self.f() as s:
        ev = s.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "REVIEW_DECISION",
                AuditEvent.entity_id == str(inv),
            )
        )

        assert ev.decision == "approve"
        assert ev.tool_result["to"] == "APPROVED"
        assert ev.actor_label.startswith("user:")
        assert verify_audit_chain(s)[0]


def test_duplicate_click_is_idempotent_and_second_decision_is_blocked(env):
    inv = env.invoice()

    a = env.decide(inv, key="same-key")
    b = env.decide(inv, key="same-key")

    assert a.id == b.id
    assert env.count(Review, Review.invoice_id == inv) == 1

    with pytest.raises(InvalidState):
        env.decide(
            inv,
            decision="reject",
            comment="changed my mind",
            key="other-key",
        )

    with pytest.raises(Conflict):
        env.decide(
            inv,
            decision="reject",
            comment="same key different action",
            key="same-key",
        )

    assert env.status(inv) == "APPROVED"


def test_validation_rules_for_comments_and_state(env):
    inv = env.invoice()

    with pytest.raises(ValidationFailed):
        env.decide(inv, decision="reject", comment="no")

    with pytest.raises(ValidationFailed):
        env.decide(inv, decision="launch", comment="valid comment")

    with pytest.raises(InvalidState):
        env.decide(env.invoice("RECEIVED"))

    with pytest.raises(InvalidState):
        env.decide(env.invoice("PAID"))

    with self.f() as s:
        # Open critical exception requires written justification.
        s.add(
            ExceptionRecord(
                invoice_id=inv,
                exception_type="matching",
                severity="critical",
                rule_id="MATCH_PRICE",
                status="OPEN",
            )
        )
        s.commit()

    with pytest.raises(ValidationFailed):
        env.decide(inv, comment="ok")

    assert (
        env.decide(
            inv,
            comment="Price confirmed by phone with vendor.",
        ).decision
        == "approve"
    )


# ---------------------------------------------------------------- payments need approval


def test_payment_without_approval_is_blocked_and_never_reaches_the_erp(
    env, erp
):
    core, client = erp

    for status in ("RECEIVED", "AWAITING_REVIEW", "PROCESSING"):
        inv = env.invoice(status)

        with pytest.raises(ApprovalRequired):
            env.pay(client, inv)

    rejected = env.invoice()
    env.decide(rejected, decision="reject", comment="wrong vendor entirely")

    with pytest.raises(ApprovalRequired):
        env.pay(client, rejected)

    assert core.payments == {}
    assert (
        env.count(
            IntegrationRecord,
            IntegrationRecord.integration == "erp_payment",
        )
        == 0
    )

    with self.f() as s:
        assert (
            s.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "PAYMENT_BLOCKED"
                )
            )
            >= 4
        )


def test_payment_requires_reviewer_or_admin_role(env, erp):
    _, client = erp
    inv = env.invoice()

    env.decide(inv)

    for who in ("clerk", "auditor"):
        with pytest.raises(PermissionDenied):
            env.pay(client, inv, who)

    assert env.status(inv) == "APPROVED"


def test_approved_invoice_is_paid_exactly_once_even_when_retried(env, erp):
    core, client = erp
    inv = env.invoice()

    env.decide(inv)

    first = env.pay(client, inv)
    again = env.pay(client, inv)

    assert first["status"] == "PAID"
    assert again["status"] == "PAID"
    assert again["replayed"]
    assert first["payment_id"] == again["payment_id"]

    assert len(core.payments) == 1
    assert env.status(inv) == "PAID"

    assert (
        env.count(
            IntegrationRecord,
            IntegrationRecord.invoice_id == inv,
            IntegrationRecord.integration == "erp_payment",
        )
        == 1
    )


def test_erp_outage_leaves_invoice_pending_not_paid_and_recovers_without_duplicates(
    env, erp
):
    core, client = erp
    inv = env.invoice()

    env.decide(inv)

    with self.f() as s:
        before = s.get(Invoice, inv).grand_total

    core.handle("POST", "/admin/simulate", {}, {"mode": "down"})

    r = env.pay(client, inv)

    assert r["status"] == "PAYMENT_PENDING"
    assert r["retry"]
    assert env.status(inv) == "PAYMENT_PENDING"
    assert core.payments == {}

    # Retry during the outage: still safe.
    r = env.pay(client, inv)

    assert r["status"] == "PAYMENT_PENDING"
    assert (
        env.count(
            IntegrationRecord,
            IntegrationRecord.invoice_id == inv,
        )
        == 1
    )

    core.handle("POST", "/admin/simulate", {}, {"mode": "normal"})

    assert env.pay(client, inv)["status"] == "PAID"
    assert len(core.payments) == 1

    with self.f() as s:
        assert s.get(Invoice, inv).grand_total == before
        assert verify_audit_chain(s)[0]


def test_erp_rejection_is_recorded_and_not_marked_paid(env, erp):
    core, client = erp
    inv = env.invoice()

    env.decide(inv)

    with self.f() as s:
        # Invalid code => ERP answers 422.
        s.execute(
            update(Invoice)
            .where(Invoice.id == inv)
            .values(currency="usd")
        )
        s.commit()

    with pytest.raises(PaymentError) as e:
        env.pay(client, inv)

    assert e.value.status == 422
    assert env.status(inv) == "PAYMENT_PENDING"
    assert core.payments == {}