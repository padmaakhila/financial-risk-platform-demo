"""Runs the real workflow against a seeded SQLite database with the real mock vendor service."""
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.agents.llm import FakeProvider, LLMUnavailable
from backend.agents.tools import ToolRegistry
from backend.agents.workflow import WorkflowConfig, WorkflowContext, initial_state, run_workflow
from backend.agents.workflow_db import latest_checkpoint, make_db_tools
from backend.database.session import make_engine, session_scope
from backend.integrations.clients import VendorVerificationClient
from backend.integrations.mock_server import start_in_thread
from backend.integrations.vendor_mock_core import VendorMock
from backend.models import AiOutput, Base, ExceptionRecord, IntegrationRecord, Invoice, LlmUsage, ScenarioGroundTruth, WorkflowCheckpoint
from backend.services.audit import verify_audit_chain
from scripts.generate_data import build_dataset
from scripts.seed_database import seed

DS = build_dataset(42)


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "wf.db"
    engine = make_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    f = sessionmaker(bind=engine, expire_on_commit=False)
    with session_scope(f) as s:
        seed(s, DS)
    core = VendorMock.from_dataset(DS, timeout_delay=1.0)
    srv, url = start_in_thread(core)
    yield f, core, VendorVerificationClient(url, timeout=0.5, sleep=lambda s: None)
    srv.shutdown()


def run_for(setup, scenario, provider=None, nth=0):
    f, core, client = setup
    with session_scope(f) as s:
        gt = s.scalars(select(ScenarioGroundTruth).where(ScenarioGroundTruth.scenario_code == scenario, ScenarioGroundTruth.invoice_id.is_not(None))
                       .order_by(ScenarioGroundTruth.id)).all()[nth]
        inv_id, expected = gt.invoice_id, gt.expected
    ctx = WorkflowContext(ToolRegistry(make_db_tools(f, client)), provider or FakeProvider([LLMUnavailable("no ollama")]), WorkflowConfig(llm_timeout=1))
    state = run_workflow(ctx, initial_state(inv_id))
    return inv_id, expected, state


def rules_of(f, inv_id):
    with session_scope(f) as s:
        return {e.rule_id for e in s.scalars(select(ExceptionRecord).where(ExceptionRecord.invoice_id == inv_id))}


@pytest.mark.parametrize("scenario", ["S01_CLEAN", "S04_LINE_TOTAL", "S05_TAX_CALC", "S06_GRAND_TOTAL", "S07_PRICE_DIFF", "S09_QTY_GT_GRN",
                                      "S10_MISSING_PO", "S11_MISSING_GRN", "S12_PARTIAL_GRN", "S13_BAD_TAX_ID", "S14_BAD_BANK", "S15_MISSING_FIELDS",
                                      "S19_PROMPT_INJECTION", "S02_DUP_EXACT", "S03_DUP_FUZZY"])
def test_workflow_reproduces_ground_truth_and_reaches_review(setup, scenario):
    f = setup[0]
    inv_id, expected, state = run_for(setup, scenario)
    assert rules_of(f, inv_id) == set(expected["rules"]) | set(expected["warnings"])
    with session_scope(f) as s:
        assert s.get(Invoice, inv_id).status == "AWAITING_REVIEW"
        out = s.scalar(select(AiOutput).where(AiOutput.invoice_id == inv_id))
        assert out.source == "template" and out.summary


def test_checkpoints_audit_usage_and_chain(setup):
    f = setup[0]
    inv_id, _, _ = run_for(setup, "S07_PRICE_DIFF", nth=1)
    with session_scope(f) as s:
        rows = s.scalars(
            select(WorkflowCheckpoint)
            .where(WorkflowCheckpoint.invoice_id == inv_id)
            .order_by(WorkflowCheckpoint.id)
        ).all()

        print([(row.node, row.state) for row in rows])
        assert len(rows) == 9
        assert s.scalar(select(LlmUsage.outcome).where(LlmUsage.invoice_id == inv_id)) == "unavailable"
        assert verify_audit_chain(s)[0]
    assert latest_checkpoint(f, inv_id)[0] == "audit"


def test_vendor_outage_does_not_break_the_case(setup):
    f, core, _ = setup
    core.handle("POST", "/admin/simulate", {}, {"mode": "down"})
    try:
        inv_id, _, state = run_for(setup, "S21_VENDOR_OUTAGE")
    finally:
        core.handle("POST", "/admin/reset", {}, {})
    with session_scope(f) as s:
        assert s.get(Invoice, inv_id).status == "AWAITING_REVIEW"
        assert s.scalar(select(IntegrationRecord.status).where(IntegrationRecord.invoice_id == inv_id)) == "UNAVAILABLE"
        assert any("unavailable" in c for c in s.scalar(select(AiOutput.caveats).where(AiOutput.invoice_id == inv_id)))


def test_rerunning_the_workflow_on_a_reviewed_invoice_changes_nothing(setup):
    f = setup[0]
    inv_id, _, _ = run_for(setup, "S01_CLEAN", nth=1)
    _, _, state = run_for(setup, "S01_CLEAN", nth=1)
    assert state["status"] == "HALTED"
    with session_scope(f) as s:
        assert s.scalar(select(func.count(AiOutput.id)).where(AiOutput.invoice_id == inv_id)) == 1
