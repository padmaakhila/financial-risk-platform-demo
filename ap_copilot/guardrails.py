
"""Prompt-injection handling for untrusted text and validation of LLM output.

Financial answers use strict evidence-grounded validation.
General answers use separate safety validation so normal educational
answers and programming examples are supported.
Everything here is enforced in code; prompts are only a second line.
"""
from __future__ import annotations

import json
import re
from typing import Iterable, Optional, Set, Tuple

from . import config
from .pii import contains_sensitive, redact_text


# ---------------------------------------------------------------------------
# Injection detection
# ---------------------------------------------------------------------------

INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|system|your)\s+(?:instructions?|rules?|prompts?|directions?)",
    r"disregard\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|system|your)?\s*(?:instructions?|rules?|prompts?)",
    r"forget\s+(?:everything|all|your)\s+(?:instructions?|rules?|above|previous)",
    r"you\s+are\s+now\s+(?:a|an|the|in)\b",
    r"\bnew\s+instructions?\s*:",
    r"(?:reveal|show|print|repeat|output|leak|display|tell\s+me)\s+(?:me\s+)?(?:your|the|its)\s+(?:hidden\s+|secret\s+|full\s+)?(?:system\s+|developer\s+|initial\s+)?(?:prompt|instructions?|rules?)",
    r"\bsystem\s+prompt\b",
    r"\bdeveloper\s+(?:message|mode)\b",
    r"\bjailbreak\b|\bdan\s+mode\b",
    r"\boverride\s+(?:the\s+)?(?:security|safety|rules?|permissions?|policy)",
    r"(?:reveal|print|show|send|output)\s+(?:the\s+)?(?:secrets?|passwords?|api[\s_-]?keys?|tokens?|jwt|credentials)",
    r"<\s*/?\s*(?:system|assistant|instructions?)\s*>",
    r"^\s*#{1,3}\s*system\b",
    r"\bbegin\s+system\b",
    r"\bact\s+as\s+(?:an?\s+)?(?:admin|administrator|root|developer|unrestricted)",
]

_INJ = re.compile(
    "|".join("(?:%s)" % pattern for pattern in INJECTION_PATTERNS),
    re.I | re.M,
)

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
INJECTION_MARK = "[instruction-like text removed]"


def detect_injection(text: Optional[str]) -> bool:
    return bool(text) and bool(_INJ.search(text))


def neutralize(text: str) -> str:
    return _INJ.sub(INJECTION_MARK, text)


def sanitize_untrusted(value, limit: int = config.MAX_TEXT_CHARS) -> str:
    """Sanitize database, OCR, and user-provided text before prompt insertion."""
    if value is None:
        return ""

    value = _CTRL.sub(" ", str(value))
    value = " ".join(value.split())
    value = redact_text(value)
    value = neutralize(value)
    value = value.replace("<", "(").replace(">", ")")
    value = value.replace("](", "] (")
    return value[:limit]


# ---------------------------------------------------------------------------
# Shared output patterns
# ---------------------------------------------------------------------------

ID_TOKEN = re.compile(r"\b[A-Za-z]{2,8}(?:[-_/][A-Za-z0-9]+)+\b")
_NUM = re.compile(r"\d[\d,]*\.?\d{1,2}|\d{4,}")

_ACTION_CLAIM = re.compile(
    r"\b(?:i\s+(?:have|'ve|will|'ll|am going to)|has\s+been|have\s+been|"
    r"was\s+successfully)\s+"
    r"(?:now\s+)?(?:approved|rejected|paid|released|deleted|updated|"
    r"modified|changed|escalated|submitted)\b",
    re.I,
)

_RECOMMEND_DECISION = re.compile(
    r"\b(?:you\s+should|i\s+recommend(?:\s+that\s+you)?|it\s+is|"
    r"it's|is)\s+(?:safe\s+to\s+)?(?:approve|pay|release)\b|"
    r"\bsafe\s+to\s+(?:approve|pay|release)\b|"
    r"\bshould\s+be\s+(?:approved|paid|released)\b",
    re.I,
)

_SAFETY_CLAIM = re.compile(
    r"\b(?:invoice|vendor|document)\s+is\s+"
    r"(?:safe|legitimate|genuine|clean|fraud[- ]free)\b|"
    r"\bno\s+(?:risks?|issues?|problems?)\s+(?:were\s+)?"
    r"(?:found|detected|exist)\b|"
    r"\bnothing\s+to\s+worry\b",
    re.I,
)

_LEAK = re.compile(
    r"(?i)system\s+prompt|my\s+instructions\s+(?:are|say)|"
    r"COPILOT-CANARY|developer\s+message"
)

_UNSAFE_MARKUP = re.compile(
    r"(?is)<\s*(?:script|iframe|img|object|embed|form|a\b)|"
    r"!\[[^\]]*\]\([^)]*\)|"
    r"\]\(\s*(?:https?:|javascript:)|"
    r"javascript:|data:text"
)

# Plain URLs are rejected in strict financial answers.
# General answers may still include normal educational links.
_UNSAFE_URL = re.compile(r"(?i)\bhttps?://")

_TOOL_STRUCT = re.compile(
    r'(?i)"(?:tool|tool_call|function_call|action|sql|command)"\s*:'
)


def id_tokens(text: str) -> Set[str]:
    return {
        token.upper()
        for token in ID_TOKEN.findall(text or "")
        if any(char.isdigit() for char in token)
    }


def _numbers(text: str) -> Set[str]:
    return {
        number.replace(",", "")
        for number in _NUM.findall(text or "")
    }


# ---------------------------------------------------------------------------
# Strict financial answer validation
# ---------------------------------------------------------------------------

def validate_output(
    raw,
    grounding_text: str,
    extra_allowed: Iterable[str] = (),
) -> Tuple[bool, str, str]:
    """Validate an LLM answer against retrieved financial evidence.

    Every identifier and number must be supported by retrieved evidence
    or explicitly allowed user-provided identifiers.
    """
    if not isinstance(raw, str):
        return False, "", "not_text"

    text = raw.strip()

    if not text:
        return False, "", "empty"

    if len(text) > config.MAX_ANSWER_CHARS:
        return False, "", "too_long"

    if _LEAK.search(text):
        return False, "", "prompt_leak"

    if contains_sensitive(text):
        return False, "", "sensitive_data"

    if (
        "```" in text
        or _UNSAFE_MARKUP.search(text)
        or _UNSAFE_URL.search(text)
    ):
        return False, "", "unsafe_markup"

    if text[:1] in "{[" or _TOOL_STRUCT.search(text):
        try:
            json.loads(text)
            return False, "", "structured_output"
        except ValueError:
            if _TOOL_STRUCT.search(text):
                return False, "", "structured_output"

    if _ACTION_CLAIM.search(text):
        return False, "", "action_claim"

    if _RECOMMEND_DECISION.search(text):
        return False, "", "decision_recommendation"

    if _SAFETY_CLAIM.search(text):
        return False, "", "unsupported_safety_claim"

    allowed = id_tokens(grounding_text) | {
        item.upper() for item in extra_allowed
    }

    for token in id_tokens(text):
        if token not in allowed:
            return False, "", "unsupported_identifier"

    grounded_numbers = (
        _numbers(grounding_text)
        | _numbers(" ".join(extra_allowed))
    )
    grounding_without_commas = (grounding_text or "").replace(",", "")

    for number in _numbers(text):
        if (
            number not in grounded_numbers
            and number not in grounding_without_commas
        ):
            return False, "", "unsupported_number"

    return True, text, "ok"


# ---------------------------------------------------------------------------
# General-purpose answer validation
# ---------------------------------------------------------------------------

def validate_general_output(raw) -> Tuple[bool, str, str]:
    """Validate general AI answers without requiring database grounding.

    General answers may contain normal code examples and explanations.
    This validator still blocks prompt leaks, sensitive data, unsafe
    HTML/markup, tool-call structures, and claims of financial actions.
    """
    if not isinstance(raw, str):
        return False, "", "not_text"

    text = raw.strip()

    if not text:
        return False, "", "empty"

    if len(text) > config.MAX_ANSWER_CHARS:
        return False, "", "too_long"

    if _LEAK.search(text):
        return False, "", "prompt_leak"

    if contains_sensitive(text):
        return False, "", "sensitive_data"

    if _UNSAFE_MARKUP.search(text):
        return False, "", "unsafe_markup"

    if _TOOL_STRUCT.search(text):
        try:
            json.loads(text)
            return False, "", "structured_output"
        except ValueError:
            return False, "", "structured_output"

    if _ACTION_CLAIM.search(text):
        return False, "", "action_claim"

    if _RECOMMEND_DECISION.search(text):
        return False, "", "decision_recommendation"

    if _SAFETY_CLAIM.search(text):
        return False, "", "unsupported_safety_claim"

    return True, text, "ok"
