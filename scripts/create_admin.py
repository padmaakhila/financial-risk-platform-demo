"""Create the first administrator interactively (password is typed, never stored in shell history).
   python -m scripts.create_admin [--username admin]"""
import argparse
import getpass
import re

from sqlalchemy import select

from backend.core.security import hash_password
from backend.database.session import session_scope
from backend.models import User
from backend.services.audit import append_audit_event
from scripts.init_db import init_db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--username", default="admin")
    ap.add_argument("--role", default="admin", choices=["admin", "reviewer", "ap_clerk", "auditor"])
    a = ap.parse_args()
    if not re.fullmatch(r"[a-z0-9_.-]{3,64}", a.username):
        raise SystemExit("Username must be 3-64 characters: a-z, 0-9, . _ -")
    pw = getpass.getpass("Password (10+ characters, letters and digits): ")
    if pw != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match.")
    if len(pw) < 10 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise SystemExit("Password must be at least 10 characters with letters and digits.")
    init_db()
    with session_scope() as s:
        if s.scalar(select(User.id).where(User.username == a.username)):
            raise SystemExit(f"User '{a.username}' already exists.")
        u = User(username=a.username, role=a.role, password_hash=hash_password(pw))
        s.add(u)
        s.flush()
        append_audit_event(s, actor_id=None, actor_label="system:create_admin", action="USER_CREATED", entity_type="user", entity_id=u.id, details={"username": a.username, "role": a.role})
    print(f"Created {a.role} '{a.username}'.")


if __name__ == "__main__":
    main()
