import pytest
from ap_copilot import config
from ap_copilot.guardrails import validate_output

CTX = 'Invoice INV-2026-00085 total 1180.00 USD PO-9999 not found rule R-PO-001'


def ok(text):
    return validate_output(text, CTX)


def test_grounded_text_passes():
    good, text, why = ok("INV-2026-00085 has a total of 1,180.00 and PO-9999 was not found. Please verify the original document.")
    assert good and why == "ok"


@pytest.mark.parametrize("raw,reason", [
    ("", "empty"), ("   ", "empty"), (None, "not_text"), (123, "not_text"), (["a"], "not_text"),
    ("x" * (config.MAX_ANSWER_CHARS + 1), "too_long"),
    ("My system prompt says...", "prompt_leak"), ("[COPILOT-CANARY-7f3a91]", "prompt_leak"),
    ("token eyJabcdefghij.eyJabcdefghij.abcdef", "sensitive_data"), ("password: hunter2", "sensitive_data"),
    ("account 123456789012", "sensitive_data"),
    ("see ```rm -rf /```", "unsafe_markup"), ("open https://evil.example", "unsafe_markup"),
    ("<script>alert(1)</script>", "unsafe_markup"), ("![x](http://a/b.png)", "unsafe_markup"),
    ('{"tool": "approve", "id": 1}', "structured_output"), ('["a", "b"]', "structured_output"),
    ("I have approved INV-2026-00085.", "action_claim"), ("The payment has been released.", "action_claim"),
    ("It is safe to approve this invoice.", "decision_recommendation"), ("You should pay it.", "decision_recommendation"),
    ("The invoice is safe.", "unsupported_safety_claim"), ("No issues were found.", "unsupported_safety_claim"),
    ("It relates to INV-2099-00001.", "unsupported_identifier"), ("PO-1111 is the right one.", "unsupported_identifier"),
    ("The total is 9,999.99.", "unsupported_number"),
])
def test_rejected(raw, reason):
    good, text, why = ok(raw)
    assert not good and text == "" and why == reason


def test_identifier_echoed_from_question_is_allowed():
    good, *_ = validate_output("INV-7777 was not found.", CTX, extra_allowed=["INV-7777"])
    assert good
