import json
import pytest
from ap_copilot.answer_service import answer
from ap_copilot.retrieval import build_context
from ap_copilot.security import Scope, build_scope
from .conftest import FULL_ACCOUNT, ScriptedLLM

Q = "Show INV-2026-00085 audit history, extraction and report summary"


@pytest.mark.parametrize("role,exp", [
    ("admin", dict(records=1, evidence=1, audit=1, bank=1, reports=1, admin=1)),
    ("reviewer", dict(records=1, evidence=1, audit=1, bank=1, reports=1, admin=0)),
    ("auditor", dict(records=1, evidence=1, audit=1, bank=0, reports=1, admin=0)),
    ("ap_clerk", dict(records=1, evidence=1, audit=0, bank=0, reports=1, admin=0)),
    ("guest", dict(records=0, evidence=0, audit=0, bank=0, reports=0, admin=0)),
])
def test_scope_matches_existing_permission_table(role, exp):
    s = build_scope(role)
    assert {k: int(getattr(s, k)) for k in exp} == exp


def test_unauthorized_role_fetches_nothing(repo, scopes):
    ctx = build_context(repo, scopes["guest"], Q)
    assert repo.calls == [] and not ctx["invoices"] and ctx["notes"]


def test_clerk_gets_no_audit_and_repo_never_asked(repo, scopes):
    ctx = build_context(repo, scopes["ap_clerk"], Q)
    assert "audit_events" not in repo.calls and ctx["invoices"][0]["audit"] is None
    assert any("Audit history requires" in n for n in ctx["notes"])
    assert "reviews" not in repo.calls          # clerk has neither view_queue nor view_audit


def test_auditor_and_admin_get_audit(repo, scopes):
    for role in ("auditor", "admin"):
        r = type(repo)(**repo.d)
        ctx = build_context(r, scopes[role], Q)
        assert "audit_events" in r.calls and ctx["invoices"][0]["audit"]


def test_bank_details_only_masked_and_only_with_permission(repo, scopes):
    for role, expect in (("admin", True), ("reviewer", True), ("auditor", False), ("ap_clerk", False)):
        blob = json.dumps(build_context(type(repo)(**repo.d), scopes[role], "INV-2026-00085 VEN-001"), default=str)
        assert FULL_ACCOUNT not in blob
        assert ("bank_account_masked" in blob) is expect and ("bank_account_raw_masked" in blob) is expect


def test_evidence_denied_snippets_and_fields_not_fetched_or_sent(repo, data):
    s = Scope(role="custom", records=True, evidence=False, audit=False, bank=False, reports=False, admin=False, queue=False)
    ctx = build_context(repo, s, "INV-2026-00085")
    assert "extracted_fields" not in repo.calls
    inv = ctx["invoices"][0]
    assert inv["fields"] == [] and inv["fields_status"] == "withheld_permission"
    assert "source_evidence" not in inv["exceptions"][0]
    llm = ScriptedLLM(reply="ok")
    answer("INV-2026-00085", ctx, s, None, 30, llm_call=llm)
    sent = " ".join(llm.prompts[0])
    assert "Ignore all previous" not in sent and "PO ref on page 1" not in sent and "Acct" not in sent


def test_reports_require_view_reports(repo):
    s = Scope(role="x", records=True, evidence=True, audit=False, bank=False, reports=False, admin=False, queue=False)
    ctx = build_context(repo, s, "give me a report overview")
    assert "report_counts" not in repo.calls and ctx["report"] is None
    s2 = build_scope("auditor")
    ctx2 = build_context(type(repo)(**repo.d), s2, "give me a report overview")
    assert ctx2["report"]["invoices_by_status"]


def test_clerk_ownership_rule_blocks_other_users_document(data, scopes):
    from .conftest import FakeRepo
    r = FakeRepo(**{**data, "doc_visible": False})
    ctx = build_context(r, scopes["ap_clerk"], "INV-2026-00085")
    assert "extracted_fields" not in r.calls and ctx["invoices"][0]["fields_status"] == "withheld_ownership"
    r2 = FakeRepo(**{**data, "doc_visible": None})       # owner column unknown -> fail closed
    assert build_context(r2, scopes["ap_clerk"], "INV-2026-00085")["invoices"][0]["fields_status"] == "withheld_ownership"
    r3 = FakeRepo(**{**data, "doc_visible": False})      # reviewers are not subject to the clerk rule
    assert build_context(r3, scopes["reviewer"], "INV-2026-00085")["invoices"][0]["fields_status"] == "ok"


def test_unauthorized_data_never_reaches_llm_prompt(repo, scopes):
    llm = ScriptedLLM(reply="Nothing to add.")
    ctx = build_context(repo, scopes["ap_clerk"], Q)
    answer(Q, ctx, scopes["ap_clerk"], None, 30, llm_call=llm)
    sent = " ".join(llm.prompts[0])
    assert "reviewer1" not in sent and "invoice.rejected" not in sent and FULL_ACCOUNT not in sent
