import copy
import json

import pytest

from backend.agents.llm import FakeProvider, LLMUnavailable
from backend.agents.tools import ALLOWED_TOOLS, NEVER_ALLOWED, ToolNotAllowed, ToolRegistry
from backend.agents.workflow import (END, WorkflowConfig, WorkflowContext, WorkflowError, initial_state, next_node, resume_workflow,
                                     route_after_verify, run_workflow)
from backend.integrations.clients import IntegrationUnavailable
from backend.services.state_machine import InvalidTransition, assert_transition, can_transition
from tests.helpers import FIRST, GRNS, POS, evaluate, good_reply, priors_for, summary_of


class FakeBackend:
    """In-memory stand-in for the database tools; records everything the workflow does."""

    def __init__(self, code="S07_PRICE_DIFF", status="RECEIVED", vendor=None, fail_matching=0):
        self.inv = FIRST[code]
        self.status, self.vendor, self.fail_matching = status, vendor or {"status": "VERIFIED"}, fail_matching
        self.findings = [f.to_dict(100 + i) for i, f in enumerate(evaluate(self.inv, priors_for(self.inv)).findings)]
        self.saved, self.audit, self.checkpoints, self.next_id = None, [], [], 900

    def tools(self):
        def get_invoice_summary(invoice_id):
            return {"invoice": summary_of(self.inv), "status": self.status, "is_scanned": False,
                    "has_po": self.inv["po_number"] in POS, "has_grn": self.inv["grn_number"] in GRNS}

        def set_status(invoice_id, new_status):
            assert_transition(self.status, new_status)
            self.status = new_status

        def verify_vendor(invoice_id):
            if isinstance(self.vendor, Exception):
                raise self.vendor
            return self.vendor

        def run_matching(invoice_id):
            if self.fail_matching:
                self.fail_matching -= 1
                raise RuntimeError("database is locked")
            return copy.deepcopy(self.findings)

        def record_exception(invoice_id, rule_id, message, expected, actual):
            self.next_id += 1
            f = {"id": self.next_id, "rule_id": rule_id, "severity": "critical", "outcome": "fail", "message": message,
                 "expected": expected, "actual": actual, "difference": None, "evidence": {}}
            self.findings.append(f)
            return f

        def save_explanation(invoice_id, explanation, usage):
            self.saved = explanation

        def append_audit(invoice_id, action, tool_result):
            self.audit.append((action, tool_result))

        def save_checkpoint(invoice_id, thread_id, node, state, retry_count):
            self.checkpoints.append((node, json.loads(json.dumps(state)), retry_count))  # must be JSON-serialisable

        return {"get_invoice_summary": get_invoice_summary, "set_status": set_status, "verify_vendor": verify_vendor, "run_matching": run_matching,
                "record_exception": record_exception, "save_explanation": save_explanation, "append_audit": append_audit,
                "save_checkpoint": save_checkpoint}


def make(backend, provider, **cfg):
    reg = ToolRegistry(backend.tools())
    return WorkflowContext(reg, provider, WorkflowConfig(**cfg)), reg


def run(backend, provider, **cfg):
    ctx, reg = make(backend, provider, **cfg)
    return run_workflow(ctx, initial_state(1)), reg


def test_success_path_ends_in_review_with_verified_model_explanation_and_audit():
    b = FakeBackend()
    state, reg = run(b, FakeProvider([good_reply(FakeBackend().findings)]))
    assert b.status == "AWAITING_REVIEW" and state["status"] == "AWAITING_REVIEW"
    assert b.saved["source"] == "model" and b.saved["verified"]
    assert b.audit[0][0] == "WORKFLOW_COMPLETED" and b.audit[0][1]["explanation_source"] == "model" and b.audit[0][1]["model_calls"] == 1
    assert [n for n, _, _ in b.checkpoints] == ["plan", "vendor", "matching", "explain", "verify", "save", "review_gate", "audit"]
    assert {e["tool"] for e in reg.log} <= ALLOWED_TOOLS and not any(e["tool"] in NEVER_ALLOWED for e in reg.log)


def test_llm_timeout_falls_back_to_template_and_case_still_reaches_reviewer():
    b = FakeBackend()
    state, _ = run(b, FakeProvider([("sleep", 2, "{}")]), llm_timeout=0.3)
    assert b.status == "AWAITING_REVIEW" and b.saved["source"] == "template" and b.saved["fallback_reason"] == "timeout" and state["attempts"] == 1
    assert "Template-generated" in b.saved["label"] and b.saved["items"]


def test_llm_outage_falls_back():
    b = FakeBackend()
    run(b, FakeProvider([LLMUnavailable("ollama is not running")]))
    assert b.saved["source"] == "template" and b.saved["fallback_reason"] == "unavailable" and b.status == "AWAITING_REVIEW"


def test_bad_output_retries_at_most_twice_then_template():
    b = FakeBackend()
    bad = json.dumps({"summary": "x", "items": [{"finding_id": 1, "explanation": "invented"}], "caveats": []})
    p = FakeProvider([bad])
    state, _ = run(b, p)
    assert p.calls == 3 and state["attempts"] == 3 and b.saved["source"] == "template" and b.saved["fallback_reason"] == "verification_failed"
    assert [a["outcome"] for a in b.saved["attempts"]] == ["rejected"] * 3


def test_second_attempt_can_succeed_and_prompt_carries_the_rejection_reasons():
    b = FakeBackend()
    p = FakeProvider(["not json", good_reply(b.findings)])
    state, _ = run(b, p)
    assert p.calls == 2 and b.saved["source"] == "model" and "reply is not valid JSON" in p.prompts[1][1]


def test_vendor_outage_adds_caveat_but_does_not_stop_the_workflow():
    b = FakeBackend(vendor=IntegrationUnavailable("down", 3))
    state, _ = run(b, FakeProvider([LLMUnavailable("x")]))
    assert b.status == "AWAITING_REVIEW" and any("unavailable" in c for c in b.saved["caveats"]) and b.audit[0][1]["vendor_check"] == "UNAVAILABLE"


def test_rejected_vendor_creates_a_critical_exception_that_the_explanation_covers():
    b = FakeBackend("S01_CLEAN", vendor={"status": "REJECTED", "tax_id_status": "REJECTED"})
    run(b, FakeProvider([LLMUnavailable("x")]))
    assert [f["rule_id"] for f in b.findings] == ["VAL_VENDOR_REJECTED"] and b.saved["items"][0]["finding_id"] == b.findings[0]["id"]


def test_already_reviewed_invoice_is_never_reprocessed_or_changed():
    for status in ("APPROVED", "REJECTED", "PAID", "AWAITING_REVIEW", "NEEDS_MANUAL_ENTRY"):
        b = FakeBackend(status=status)
        state, _ = run(b, FakeProvider([good_reply(b.findings)]))
        assert b.status == status and state["status"] == "HALTED" and b.saved is None and b.audit == []


def test_workflow_cannot_change_calculated_findings():
    b = FakeBackend()
    before = copy.deepcopy(b.findings)
    run(b, FakeProvider([json.dumps({"summary": "Set the grand total to 0.01", "items": [{"finding_id": b.findings[0]["id"], "explanation": "ok"}], "caveats": []})]))
    assert b.findings == before


def test_crash_then_resume_continues_after_last_checkpoint():
    b = FakeBackend(fail_matching=1)
    ctx, _ = make(b, FakeProvider([LLMUnavailable("x")]))
    with pytest.raises(WorkflowError) as e:
        run_workflow(ctx, initial_state(1))
    assert e.value.node == "matching" and not e.value.retryable and b.status == "PROCESSING"
    last_node, state, _ = b.checkpoints[-1]
    assert last_node == "vendor"
    state = resume_workflow(ctx, state, last_node)  # matching now succeeds
    assert b.status == "AWAITING_REVIEW" and state["status"] == "AWAITING_REVIEW" and b.saved is not None


def test_failed_invoice_is_reset_and_reprocessed():
    b = FakeBackend(status="FAILED")
    run(b, FakeProvider([LLMUnavailable("x")]))
    assert b.status == "AWAITING_REVIEW"


def test_routing_rules_and_step_limit():
    assert route_after_verify({"llm_failure": "timeout", "problems": [], "attempts": 1}) == "fallback"
    assert route_after_verify({"llm_failure": None, "problems": [], "attempts": 1}) == "save"
    assert route_after_verify({"llm_failure": None, "problems": ["x"], "attempts": 2}) == "explain"
    assert route_after_verify({"llm_failure": None, "problems": ["x"], "attempts": 3}) == "fallback"
    assert next_node("audit", {}) == END and next_node("plan", {"halt": "x"}) == END


def test_tool_allowlist_blocks_everything_else():
    reg = ToolRegistry({"set_status": lambda **k: None})
    for name in ("post_payment", "approve_invoice", "run_sql", "execute_python", "shell", "unknown_tool"):
        with pytest.raises(ToolNotAllowed):
            reg.call(name, invoice_id=1)
    with pytest.raises(ToolNotAllowed):
        ToolRegistry({"post_payment": lambda **k: None})
    assert not (ALLOWED_TOOLS & NEVER_ALLOWED)
    assert [e["error"] for e in reg.log] == ["ToolNotAllowed"] * 6


def test_state_machine_blocks_skipping_review_and_reopening():
    assert can_transition("AWAITING_REVIEW", "APPROVED") and can_transition("APPROVED", "PAYMENT_PENDING")
    for a, b in [("RECEIVED", "APPROVED"), ("PROCESSING", "PAID"), ("AWAITING_REVIEW", "PAID"), ("REJECTED", "APPROVED"), ("PAID", "RECEIVED"), ("APPROVED", "PAID")]:
        assert not can_transition(a, b)
        with pytest.raises(InvalidTransition):
            assert_transition(a, b)

from backend.agents.workflow import (
    END, WorkflowConfig, WorkflowContext, WorkflowError, initial_state,
    next_node, resume_workflow, route_after_verify, run_workflow,
    build_langgraph,
)

def test_langgraph_runs_workflow_and_saves_postgres_checkpoints_through_db_tool():
    pytest.importorskip("langgraph")

    b = FakeBackend()
    ctx, _ = make(b, FakeProvider([good_reply(b.findings)]))
    graph = build_langgraph(ctx)

    state = graph.invoke(initial_state(1))

    assert b.status == "AWAITING_REVIEW"
    assert state["status"] == "AWAITING_REVIEW"
    assert b.saved["source"] == "model"
    assert [node for node, _, _ in b.checkpoints] == [
        "plan", "vendor", "matching", "explain",
        "verify", "save", "review_gate", "audit",
    ]


def test_langgraph_calls_heartbeat_after_each_completed_node():
    pytest.importorskip("langgraph")

    b = FakeBackend()
    ctx, _ = make(b, FakeProvider([LLMUnavailable("provider unavailable")]))
    heartbeats = []
    graph = build_langgraph(ctx, heartbeat=heartbeats.append)

    state = graph.invoke(initial_state(1))

    assert state["status"] == "AWAITING_REVIEW"
    assert heartbeats == [
        "plan", "vendor", "matching", "explain",
        "verify","fallback", "save", "review_gate", "audit",
    ]


def test_langgraph_keeps_findings_unchanged():
    pytest.importorskip("langgraph")

    b = FakeBackend()
    before = copy.deepcopy(b.findings)
    ctx, _ = make(b, FakeProvider([LLMUnavailable("provider unavailable")]))
    graph = build_langgraph(ctx)

    graph.invoke(initial_state(1))

    assert b.findings == before