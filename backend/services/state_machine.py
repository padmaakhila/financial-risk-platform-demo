"""Invoice status state machine. All status changes go through can_transition()."""
TRANSITIONS = {
    "RECEIVED": {"PROCESSING"},
    "PROCESSING": {"AWAITING_REVIEW", "NEEDS_MANUAL_ENTRY", "FAILED", "RECEIVED"},
    "NEEDS_MANUAL_ENTRY": {"RECEIVED", "REJECTED"},
    "AWAITING_REVIEW": {"APPROVED", "REJECTED", "DOCUMENTS_REQUESTED"},
    "DOCUMENTS_REQUESTED": {"RECEIVED", "REJECTED"},
    "APPROVED": {"PAYMENT_PENDING"},
    "PAYMENT_PENDING": {"PAID"},
    "PAID": set(), "REJECTED": set(),
    "FAILED": {"RECEIVED"},
}


class InvalidTransition(Exception):
    pass


def can_transition(current: str, new: str) -> bool:
    return new in TRANSITIONS.get(current, set())


def assert_transition(current: str, new: str) -> None:
    if not can_transition(current, new):
        raise InvalidTransition(f"{current} -> {new} is not allowed")
