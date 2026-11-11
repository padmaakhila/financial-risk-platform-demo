"""Single role/permission table used by the API (and mirrored by Streamlit navigation, which only calls the API)."""
PERMISSIONS = {
    "upload": {"admin", "ap_clerk", "reviewer"},
    "view_records": {"admin", "ap_clerk", "reviewer", "auditor"},
    "view_evidence": {"admin", "ap_clerk", "reviewer", "auditor"},
    "view_bank_details": {"admin", "reviewer"},
    "process": {"admin", "ap_clerk", "reviewer"},
    "view_queue": {"admin", "reviewer"},
    "decide": {"admin", "reviewer"},
    "pay": {"admin", "reviewer"},
    "view_reports": {"admin", "ap_clerk", "reviewer", "auditor"},
    "view_audit": {"admin", "reviewer", "auditor"},
    "monitoring": {"admin", "reviewer", "auditor"},
    "admin": {"admin"},
}


def can(role: str, permission: str) -> bool:
    return role in PERMISSIONS.get(permission, set())


def mask_account(value: str | None) -> str | None:
    return None if not value else "*" * max(0, len(value) - 4) + value[-4:]
