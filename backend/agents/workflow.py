"""Workflow: request -> classification/planning -> approved tools -> verification -> response/action -> audit.

The node functions and router are plain Python (fully unit-tested); `run_workflow` executes them with a
bounded loop and writes a checkpoint after every node so an interrupted job can resume. `build_langgraph`
wires the same functions into a LangGraph StateGraph when langgraph is installed.

Application checkpoints are saved through the existing `save_checkpoint` tool, which uses the app database
(PostgreSQL in this project). This workflow never approves or pays: it only ends in AWAITING_REVIEW
(or stops for manual entry).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypedDict

from backend.agents.risk_explainer import (
    ExplanationResult,
    make_fallback,
    request_explanation,
    verify_explanation,
)
from backend.agents.tools import ToolRegistry
from backend.integrations.clients import IntegrationUnavailable
from backend.services.classifier import make_plan


class WorkflowState(TypedDict, total=False):
    invoice_id: int
    thread_id: str
    invoice: dict
    plan: list
    halt: str | None
    findings: list
    caveats: list
    vendor_check: dict
    candidate: dict | None
    problems: list
    attempts: int
    llm_failure: str | None
    usage: list
    attempt_log: list
    explanation: dict | None
    status: str


@dataclass
class WorkflowConfig:
    max_retries: int = 2  # verification retries (so at most 3 model calls)
    llm_timeout: float = 60


@dataclass
class WorkflowContext:
    tools: ToolRegistry
    provider: object
    config: WorkflowConfig


class WorkflowError(Exception):
    def __init__(self, node: str, cause: Exception):
        super().__init__(f"workflow failed in node '{node}': {type(cause).__name__}")
        self.node, self.cause = node, cause
        self.retryable = isinstance(cause, IntegrationUnavailable)


def initial_state(invoice_id: int) -> WorkflowState:
    return {
        "invoice_id": invoice_id,
        "thread_id": f"invoice-{invoice_id}",
        "halt": None,
        "findings": [],
        "caveats": [],
        "problems": [],
        "attempts": 0,
        "usage": [],
        "attempt_log": [],
        "llm_failure": None,
        "candidate": None,
        "explanation": None,
        "status": "RUNNING",
    }


# ------------------------------------------------------------------ nodes
def node_plan(s: dict, ctx: WorkflowContext) -> dict:
    info = ctx.tools.call("get_invoice_summary", invoice_id=s["invoice_id"])
    s["invoice"] = info["invoice"]
    s["plan"] = make_plan("invoice", info["is_scanned"], info["has_po"], info["has_grn"])

    if info["status"] in ("RECEIVED", "FAILED"):
        if info["status"] == "FAILED":
            ctx.tools.call("set_status", invoice_id=s["invoice_id"], new_status="RECEIVED")
        ctx.tools.call("set_status", invoice_id=s["invoice_id"], new_status="PROCESSING")
    elif info["status"] != "PROCESSING":
        # Already reviewed / waiting for manual entry: never reprocess or change it.
        s["halt"] = f"status_{info['status'].lower()}"

    return s


def node_vendor(s: dict, ctx: WorkflowContext) -> dict:
    try:
        s["vendor_check"] = ctx.tools.call("verify_vendor", invoice_id=s["invoice_id"])
    except IntegrationUnavailable:
        s["vendor_check"] = {"status": "UNAVAILABLE"}
        s["caveats"].append(
            "Vendor verification service was unavailable, so the vendor and bank details are unconfirmed."
        )
        return s

    vc = s["vendor_check"]
    if vc.get("status") in ("NOT_FOUND", "INVALID"):
        s["caveats"].append(
            "The vendor could not be confirmed by the verification service."
        )
    if vc.get("bank_status") == "MISMATCH":
        s["caveats"].append(
            "The bank details do not match the vendor verification service."
        )

    return s


def node_matching(s: dict, ctx: WorkflowContext) -> dict:
    s["findings"] = ctx.tools.call("run_matching", invoice_id=s["invoice_id"])

    if s.get("vendor_check", {}).get("tax_id_status") == "REJECTED":
        # Bank problems are already covered by VAL_BANK_* rules.
        s["findings"].append(
            ctx.tools.call(
                "record_exception",
                invoice_id=s["invoice_id"],
                rule_id="VAL_VENDOR_REJECTED",
                message="The vendor verification service rejected this vendor or bank account",
                expected="verified vendor",
                actual="REJECTED",
            )
        )

    return s


def node_explain(s: dict, ctx: WorkflowContext) -> dict:
    cand, problems, usage, failure = request_explanation(
        ctx.provider,
        s["invoice"],
        s["findings"],
        s["caveats"],
        s["problems"] or None,
        ctx.config.llm_timeout,
    )

    s["attempts"] += 1
    if usage:
        s["usage"].append(usage)

    s["llm_failure"], s["candidate"], s["problems"] = failure, cand, problems

    if failure:
        s["attempt_log"].append({"n": s["attempts"], "outcome": failure})

    return s


def node_verify(s: dict, ctx: WorkflowContext) -> dict:
    if s["llm_failure"]:
        return s

    if s["candidate"] is not None:
        s["problems"] = verify_explanation(
            s["candidate"],
            s["findings"],
            s["invoice"],
            s["caveats"],
        )

    s["attempt_log"].append(
        {
            "n": s["attempts"],
            "outcome": "verified" if not s["problems"] else "rejected",
            "problems": s["problems"],
        }
    )

    if not s["problems"]:
        candidate = s["candidate"]
        s["explanation"] = ExplanationResult(
            "model",
            candidate["summary"],
            candidate["items"],
            candidate["caveats"],
            s["attempt_log"],
            s["usage"],
        ).to_dict()

    return s


def node_fallback(s: dict, ctx: WorkflowContext) -> dict:
    reason = s["llm_failure"] or "verification_failed"
    s["explanation"] = make_fallback(
        s["invoice"],
        s["findings"],
        s["caveats"],
        reason,
        s["attempt_log"],
        s["usage"],
    ).to_dict()
    return s


def node_save(s: dict, ctx: WorkflowContext) -> dict:
    ctx.tools.call(
        "save_explanation",
        invoice_id=s["invoice_id"],
        explanation=s["explanation"],
        usage=s["usage"],
    )
    return s


def node_review_gate(s: dict, ctx: WorkflowContext) -> dict:
    # A human decides; this workflow never auto-approves.
    ctx.tools.call(
        "set_status",
        invoice_id=s["invoice_id"],
        new_status="AWAITING_REVIEW",
    )
    s["status"] = "AWAITING_REVIEW"
    return s


def node_audit(s: dict, ctx: WorkflowContext) -> dict:
    explanation = s["explanation"]
    ctx.tools.call(
        "append_audit",
        invoice_id=s["invoice_id"],
        action="WORKFLOW_COMPLETED",
        tool_result={
            "findings": len(s["findings"]),
            "explanation_source": explanation["source"],
            "fallback_reason": explanation.get("fallback_reason"),
            "model_calls": s["attempts"],
            "vendor_check": s.get("vendor_check", {}).get("status"),
            "final_status": s["status"],
        },
    )
    return s


NODES = {
    "plan": node_plan,
    "vendor": node_vendor,
    "matching": node_matching,
    "explain": node_explain,
    "verify": node_verify,
    "fallback": node_fallback,
    "save": node_save,
    "review_gate": node_review_gate,
    "audit": node_audit,
}
END = "__end__"


def route_after_plan(s: dict) -> str:
    return END if s.get("halt") else "vendor"


def route_after_verify(s: dict, max_retries: int = 2) -> str:
    if s.get("llm_failure"):
        # Timeout / outage: no retry loop, straight to deterministic template.
        return "fallback"
    if not s["problems"]:
        return "save"
    return "explain" if s["attempts"] <= max_retries else "fallback"


def next_node(current: str, s: dict, max_retries: int = 2) -> str:
    static = {
        "vendor": "matching",
        "matching": "explain",
        "explain": "verify",
        "fallback": "save",
        "save": "review_gate",
        "review_gate": "audit",
        "audit": END,
    }

    if current == "plan":
        return route_after_plan(s)
    if current == "verify":
        return route_after_verify(s, max_retries)
    return static[current]


# ------------------------------------------------------------------ runner
def run_workflow(
    ctx: WorkflowContext,
    state: dict,
    *,
    start: str = "plan",
    max_steps: int = 40,
) -> dict:
    node, steps = start, 0

    while node != END:
        steps += 1
        if steps > max_steps:
            raise WorkflowError(node, RuntimeError("step limit exceeded"))

        try:
            state = NODES[node](state, ctx)
            ctx.tools.call(
                "save_checkpoint",
                invoice_id=state["invoice_id"],
                thread_id=state["thread_id"],
                node=node,
                state=state,
                retry_count=max(0, state.get("attempts", 0) - 1),
            )
        except Exception as exc:
            raise WorkflowError(node, exc) from exc

        node = next_node(node, state, ctx.config.max_retries)

    if state.get("halt"):
        state["status"] = "HALTED"

    return state


def resume_workflow(
    ctx: WorkflowContext,
    checkpoint_state: dict,
    last_node: str,
) -> dict:
    """Continue after the last completed node (used after a crash or restart)."""
    next_step = next_node(last_node, checkpoint_state, ctx.config.max_retries)
    return (
        checkpoint_state
        if next_step == END
        else run_workflow(ctx, checkpoint_state, start=next_step)
    )


# ------------------------------------------------------------------ LangGraph wiring (same nodes, same router)
def build_langgraph(
    ctx: WorkflowContext,
    checkpointer=None,
    heartbeat: Callable[[str], None] | None = None,
):
    """Build the LangGraph workflow.

    Each completed node writes the application's checkpoint through the existing
    `save_checkpoint` tool. `heartbeat`, when supplied, is called with the node
    name after that checkpoint is saved. The app database remains the source of
    truth for resuming work.
    """
    from langgraph.graph import END as LG_END, START, StateGraph

    graph = StateGraph(WorkflowState)

    for name, fn in NODES.items():

        def run_node(state: dict, node_fn=fn, node_name=name) -> dict:
            # Copy state so the graph receives a fresh state object.
            updated_state = node_fn(dict(state), ctx)

            ctx.tools.call(
                "save_checkpoint",
                invoice_id=updated_state["invoice_id"],
                thread_id=updated_state["thread_id"],
                node=node_name,
                state=updated_state,
                retry_count=max(0, updated_state.get("attempts", 0) - 1),
            )

            if heartbeat is not None:
                heartbeat(node_name)

            return updated_state

        graph.add_node(f"n_{name}", run_node)

    graph.add_edge(START, "n_plan")

    graph.add_conditional_edges(
        "n_plan",
        lambda state: "n_end" if route_after_plan(state) == END else "n_vendor",
        {"n_end": LG_END, "n_vendor": "n_vendor"},
    )

    graph.add_edge("n_vendor", "n_matching")
    graph.add_edge("n_matching", "n_explain")
    graph.add_edge("n_explain", "n_verify")

    graph.add_conditional_edges(
        "n_verify",
        lambda state: f"n_{route_after_verify(state, ctx.config.max_retries)}",
        {
            "n_explain": "n_explain",
            "n_fallback": "n_fallback",
            "n_save": "n_save",
        },
    )

    graph.add_edge("n_fallback", "n_save")
    graph.add_edge("n_save", "n_review_gate")
    graph.add_edge("n_review_gate", "n_audit")
    graph.add_edge("n_audit", LG_END)

    return graph.compile(checkpointer=checkpointer)


def sqlite_checkpointer(path: str):
    """Optional LangGraph checkpoint store; not used for the app's PostgreSQL checkpoints."""
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    return SqliteSaver(sqlite3.connect(path, check_same_thread=False))