import pytest

from backend.integrations.clients import ErpClient, IntegrationRejected, IntegrationUnavailable, VendorVerificationClient
from backend.integrations.erp_mock_core import ErpMock
from backend.integrations.mock_server import start_in_thread
from backend.integrations.vendor_mock_core import VendorMock
from scripts.generate_data import build_dataset

DS = build_dataset(42)
V = DS["vendors"][0]
BLOCKED = next(v for v in DS["vendors"] if not v["active"])
NOSLEEP = lambda s: None
PAY = {"invoice_number": "INV-000001", "vendor_code": "V0001", "amount": "123.45", "currency": "USD", "approval_id": "7"}


def vendor_env(**kw):
    core = VendorMock.from_dataset(DS, timeout_delay=1.0)
    srv, url = start_in_thread(core)
    return core, srv, VendorVerificationClient(url, timeout=0.4, sleep=NOSLEEP, **kw)


def erp_env(**kw):
    core = ErpMock(timeout_delay=1.0)
    srv, url = start_in_thread(core)
    return core, srv, ErpClient(url, timeout=0.4, sleep=NOSLEEP, **kw)


# ---------------------------------------------------------------- vendor verification
def test_vendor_verification_outcomes():
    core, srv, c = vendor_env()
    try:
        assert c.verify(tax_id=V["tax_id"], bank_account=V["bank_account"])["status"] == "VERIFIED"
        r = c.verify(tax_id=V["tax_id"], bank_account="FB00ZZZZ0000000000")
        assert r["status"] == "REJECTED" and r["bank_status"] == "MISMATCH"
        assert c.verify(tax_id=BLOCKED["tax_id"])["status"] == "REJECTED"
        assert c.verify(tax_id="TX000000000")["status"] == "NOT_FOUND"
        assert c.verify(tax_id="bad-id")["tax_id_status"] == "INVALID_FORMAT"
        with pytest.raises(IntegrationRejected) as e:
            c.verify(tax_id="")
        assert e.value.status == 422
        assert c.healthy()
    finally:
        srv.shutdown()


def test_vendor_outage_timeout_and_flaky_behaviour():
    core, srv, c = vendor_env()
    try:
        core.handle("POST", "/admin/simulate", {}, {"mode": "down"})
        with pytest.raises(IntegrationUnavailable) as e:
            c.verify(tax_id=V["tax_id"])
        assert e.value.attempts == 3 and not c.healthy()  # 1 try + 2 bounded retries
        core.handle("POST", "/admin/simulate", {}, {"mode": "timeout"})
        with pytest.raises(IntegrationUnavailable) as e:
            c.verify(tax_id=V["tax_id"])
        assert e.value.attempts == 3
        core.handle("POST", "/admin/simulate", {}, {"mode": "flaky", "fail_n": 2})
        r = c.verify(tax_id=V["tax_id"])
        assert r["status"] == "VERIFIED" and r["_attempts"] == 3
        core.handle("POST", "/admin/simulate", {}, {"mode": "flaky", "fail_n": 5})
        with pytest.raises(IntegrationUnavailable):
            c.verify(tax_id=V["tax_id"])
        core.handle("POST", "/admin/simulate", {}, {"mode": "reject_all"})
        assert c.verify(tax_id=V["tax_id"])["status"] == "REJECTED"
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- ERP payments
def test_erp_payment_is_idempotent():
    core, srv, c = erp_env()
    try:
        first = c.post_payment(PAY, "key-1")
        assert first["_http_status"] == 201 and first["status"] == "POSTED" and first["replayed"] is False
        again = c.post_payment(PAY, "key-1")
        assert again["_http_status"] == 200 and again["payment_id"] == first["payment_id"] and again["replayed"] is True
        assert len(core.payments) == 1
    finally:
        srv.shutdown()


def test_erp_rejects_key_reuse_duplicate_approval_and_bad_input():
    core, srv, c = erp_env()
    try:
        c.post_payment(PAY, "key-1")
        for payload, key, status in [({**PAY, "amount": "999.00"}, "key-1", 409), (PAY, "key-2", 409), ({**PAY, "approval_id": "8", "amount": "0"}, "k3", 422),
                                     ({**PAY, "approval_id": "9", "amount": "-5"}, "k4", 422), ({**PAY, "approval_id": "9", "amount": 12.5}, "k5", 422),
                                     ({**PAY, "approval_id": "9", "currency": "usd"}, "k6", 422), ({k: v for k, v in PAY.items() if k != "approval_id"}, "k7", 422),
                                     ({**PAY, "approval_id": "9"}, " ", 400)]:
            with pytest.raises(IntegrationRejected) as e:
                c.post_payment(payload, key)
            assert e.value.status == status, (payload, key)
        assert len(core.payments) == 1
    finally:
        srv.shutdown()


def test_erp_outage_creates_nothing_and_recovery_posts_exactly_once():
    core, srv, c = erp_env()
    try:
        core.handle("POST", "/admin/simulate", {}, {"mode": "down"})
        with pytest.raises(IntegrationUnavailable):
            c.post_payment(PAY, "key-1")
        assert core.payments == {}
        core.handle("POST", "/admin/simulate", {}, {"mode": "normal"})
        c.post_payment(PAY, "key-1")
        c.post_payment(PAY, "key-1")
        assert len(core.payments) == 1
        core.handle("POST", "/admin/simulate", {}, {"mode": "flaky", "fail_n": 1})
        r = c.post_payment({**PAY, "approval_id": "11"}, "key-11")
        assert r["_attempts"] == 2 and len(core.payments) == 2
    finally:
        srv.shutdown()


def test_unreachable_service_is_reported_as_unavailable():
    c = ErpClient("http://127.0.0.1:9", timeout=0.3, sleep=NOSLEEP)
    with pytest.raises(IntegrationUnavailable):
        c.post_payment(PAY, "k")
    assert c.healthy() is False
