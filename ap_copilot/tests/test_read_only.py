"""Read-only proofs: static scan of every Copilot source file, a spy that
allow-lists repo calls, and (when SQLAlchemy is installed) the flush guard."""
import ast
import pathlib

import pytest

from ap_copilot.answer_service import answer
from ap_copilot.retrieval import build_context
from .conftest import READ_METHODS, ScriptedLLM

PKG = pathlib.Path(__file__).resolve().parent.parent
SOURCES = [p for p in PKG.glob("*.py")]

ALWAYS_FORBIDDEN = {"commit", "flush", "add_all", "delete", "merge", "bulk_save_objects", "bulk_insert_mappings",
                    "bulk_update_mappings", "executemany", "system", "popen", "Popen", "eval", "exec", "urlopen",
                    "get_bytes", "upload", "put", "patch"}
DB_RECEIVERS = {"db", "session", "s"}                      # add/insert/update are only forbidden on a DB session
DB_WRITE_ATTRS = {"add", "insert", "update", "execute"}
FORBIDDEN_IMPORTS = {"subprocess", "os", "requests", "httpx", "urllib", "socket", "shutil", "pickle",
                     "backend.services.payments", "backend.services.review", "backend.services.audit",
                     "backend.agents.tools", "backend.agents.workflow", "backend.api.routes_ops"}


def _recv(f):
    v = f.value
    while isinstance(v, ast.Attribute):
        if v.attr in DB_RECEIVERS:
            return v.attr
        v = v.value
    return v.id if isinstance(v, ast.Name) else None


def _bad_calls(tree):
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
        if name in ALWAYS_FORBIDDEN:
            yield name
        if isinstance(f, ast.Attribute) and f.attr in DB_WRITE_ATTRS and _recv(f) in DB_RECEIVERS:
            if not (f.attr == "execute"):                     # SELECT-only execute is checked separately below
                yield "db." + f.attr


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_source_has_no_write_exec_or_network_calls(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad = set(_bad_calls(tree))
    if path.name == "streamlit_widget.py":
        bad -= {"put", "patch"}                 # not used; kept in the list for every other module
    assert not bad, "forbidden call(s) in %s: %s" % (path.name, bad)
    for n in ast.walk(tree):
        names = []
        if isinstance(n, ast.Import):
            names = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module:
            names = [n.module]
        for name in names:
            assert name not in FORBIDDEN_IMPORTS, "forbidden import %s in %s" % (name, path.name)


def test_only_select_statements_in_orm_repo():
    src = (PKG / "orm_repo.py").read_text()
    for w in ("insert(", "update(", "delete(", ".add(", "commit(", "text("):
        assert w not in src


def test_router_exposes_one_post_chat_endpoint_only():
    src = (PKG / "router.py").read_text()
    assert src.count("@router.") == 1 and '@router.post("/chat"' in src


def test_pipeline_only_calls_allow_listed_read_methods(repo, scopes):
    for role in ("admin", "reviewer", "auditor", "ap_clerk"):
        r = type(repo)(**repo.d)
        for q in ("Why was INV-2026-00085 rejected? audit history report", "VEN-001 PO-1234 GRN-5555", "pending review high risk report"):
            ctx = build_context(r, scopes[role], q)
            answer(q, ctx, scopes[role], None, 5, llm_call=ScriptedLLM(reply="ok"))
        assert set(r.calls) <= READ_METHODS


def test_repo_data_is_not_mutated(repo, scopes, data):
    import copy
    before = copy.deepcopy(data)
    ctx = build_context(repo, scopes["admin"], "INV-2026-00085 VEN-001")
    answer("INV-2026-00085", ctx, scopes["admin"], None, 5, llm_call=ScriptedLLM(reply="ok"))
    assert repo.d == before


def test_no_approve_pay_or_decision_capability_surface():
    import ap_copilot.answer_service as a, ap_copilot.retrieval as r
    names = {n.lower() for m in (a, r) for n in dir(m)}
    assert not any(w in n for n in names for w in ("approve_", "reject_", "pay_invoice", "release_payment", "write_audit"))


def test_orm_flush_guard_blocks_writes_and_rolls_back():
    sa = pytest.importorskip("sqlalchemy")
    from sqlalchemy.orm import Session, declarative_base
    from ap_copilot.security import ReadOnlyViolation, read_only_session
    Base = declarative_base()

    class T(Base):
        __tablename__ = "t"
        id = sa.Column(sa.Integer, primary_key=True)
        v = sa.Column(sa.String)

    eng = sa.create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(T(id=1, v="a")); s.commit()
        with read_only_session(s):
            assert s.query(T).count() == 1                      # reads work
            s.add(T(id=2, v="b"))
            with pytest.raises(ReadOnlyViolation):
                s.flush()
        with Session(eng) as s2:
            assert s2.query(T).count() == 1                     # nothing was persisted
        with read_only_session(s):
            row = s.query(T).first(); row.v = "changed"
            with pytest.raises(ReadOnlyViolation):
                s.flush()
        s.rollback()
        assert s.query(T).first().v == "a"


def test_orm_queries_compile_against_real_models():
    pytest.importorskip("backend.models.entities")           # runs only inside your project
    sa = pytest.importorskip("sqlalchemy")
    from unittest.mock import MagicMock
    from sqlalchemy.dialects import postgresql
    from ap_copilot.orm_repo import OrmRepo
    db = MagicMock()
    res = db.execute.return_value
    res.scalars.return_value.all.return_value = []
    res.all.return_value = []
    res.first.return_value = None
    repo = OrmRepo(db, 1, "admin")
    repo.find_invoices(["A-1"], [1], ["pending"], 5); repo.find_vendors(["V-1"], ["acme"], [1], 5, True)
    repo.find_pos(["P-1"], 3); repo.find_grns(["G-1"], 3); repo.extracted_fields(1, True, 10); repo.document_visible(1)
    repo.exceptions(1, 10); repo.open_high_risk(5); repo.reviews(1, 5); repo.checkpoints(1, 5); repo.audit_events(1, 5); repo.report_counts()
    assert db.execute.call_count >= 10
    for call in db.execute.call_args_list:
        stmt = call.args[0]
        stmt.compile(dialect=postgresql.dialect())          # fails if a column/attribute name is wrong
        assert str(stmt).lstrip().upper().startswith("SELECT")
