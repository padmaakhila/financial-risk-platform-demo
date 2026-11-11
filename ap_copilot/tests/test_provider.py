import pytest
from ap_copilot import config
from ap_copilot.answer_service import answer, default_llm_call
from ap_copilot.retrieval import build_context
from .conftest import REAL_BACKEND, ScriptedLLM

import backend.agents.llm as llm_mod

Q = "Why was INV-2026-00085 rejected?"


@pytest.fixture
def ctx(repo, scopes):
    return build_context(repo, scopes["admin"], Q)


def run(ctx, scopes, llm, timeout=60):
    return answer(Q, ctx, scopes["admin"], object(), timeout, llm_call=llm)


def test_valid_model_text_is_appended_after_facts(ctx, scopes):
    res = run(ctx, scopes, ScriptedLLM(reply="PO-9999 was not found in the purchase order records for INV-2026-00085. Please verify."))
    assert res["mode"] == "facts+llm" and res["model_available"] and res["answer"].startswith("**Invoice:**")
    assert "AI explanation" in res["answer"]


@pytest.mark.parametrize("exc,warn,notice", [
    (llm_mod.LLMUnavailable("ollama down: secret-details"), "model_unavailable", "unavailable"),
    (llm_mod.LLMTimeout("slow"), "model_timeout", "timed out"),
    (RuntimeError("boom postgresql://u:pw@h/db"), "model_error", "unavailable"),
])
def test_model_errors_fall_back_to_facts_without_leaking(ctx, scopes, exc, warn, notice):
    res = run(ctx, scopes, ScriptedLLM(exc=exc))
    assert res["mode"] == "facts_only" and warn in res["warnings"] and notice in res["answer"]
    assert "secret-details" not in res["answer"] and "pw@" not in res["answer"]
    assert "MATCH_MISSING_PO" in res["answer"]            # real recorded facts are still delivered
    assert not res["model_available"]


@pytest.mark.parametrize("reply,warn", [("", "model_empty"), ("   ", "model_empty"), (None, "model_empty"),
                                        (12345, "invalid_output:not_text"), ("x" * 99999, "invalid_output:too_long"),
                                        ("It is " + "INV-1111-11111", "invalid_output:unsupported_identifier")])
def test_empty_or_invalid_model_output(ctx, scopes, reply, warn):
    res = run(ctx, scopes, ScriptedLLM(reply=reply))
    assert res["mode"] == "facts_only" and res["warnings"] == [warn]


def test_timeout_is_capped_to_fit_ui_client_timeout(ctx, scopes):
    llm = ScriptedLLM(reply="ok")
    run(ctx, scopes, llm, timeout=60)
    assert llm.timeouts == [config.COPILOT_MAX_LLM_SECONDS]
    llm2 = ScriptedLLM(reply="ok"); run(ctx, scopes, llm2, timeout=5)
    assert llm2.timeouts == [5.0]


def test_null_provider_degrades_gracefully(ctx, scopes):
    res = answer(Q, ctx, scopes["admin"], llm_mod.NullProvider(), 10)     # default_llm_call + existing wrapper
    assert res["mode"] == "facts_only" and "MATCH_MISSING_PO" in res["answer"]


def test_response_object_shapes_are_read(monkeypatch):
    class R: text = "hi"
    class R2: content = "yo"
    from ap_copilot.answer_service import _text_of
    assert _text_of(R()) == "hi" and _text_of(R2()) == "yo" and _text_of("s") == "s" and _text_of(object()) is None
