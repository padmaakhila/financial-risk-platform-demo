
"""Streamlit glue: session handling and API-call error handling."""
from __future__ import annotations

import os
import streamlit as st

from backend.auth.permissions import can
from ui.api_client import ApiClient, ApiProblem, Unauthorized
from ui.format import friendly_error


def base_url() -> str:
    """Get the deployed FastAPI URL without loading backend database settings."""
    try:
        return st.secrets["BACKEND_URL"].rstrip("/")
    except (KeyError, FileNotFoundError):
        return os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")


def api() -> ApiClient:
    return ApiClient(base_url(), st.session_state.get("token"))


def user() -> dict | None:
    return st.session_state.get("user")


def sign_in(username: str, password: str) -> None:
    data = ApiClient(base_url()).login(username, password)
    st.session_state["token"] = data["access_token"]
    st.session_state["user"] = {
        "username": data["username"],
        "role": data["role"],
    }


def sign_out() -> None:
    if st.session_state.get("token"):
        try:
            api().post("/api/auth/logout")
        except ApiProblem:
            pass

    for key in list(st.session_state.keys()):
        del st.session_state[key]


def require_login(permission: str | None = None) -> dict:
    u = user()
    if not u:
        st.warning("Please sign in first (open **Sign in** in the sidebar).")
        st.stop()

    if permission and not can(u["role"], permission):
        st.error(f"Your role ({u['role']}) cannot open this page.")
        st.stop()

    return u


def call(fn, *args, quiet: tuple = (), **kwargs):
    """Run an API call and handle authentication and API errors."""
    try:
        return fn(*args, **kwargs)
    except Unauthorized:
        for key in ("token", "user"):
            st.session_state.pop(key, None)

        st.warning("Your session has ended. Please sign in again.")
        st.stop()

    except ApiProblem as e:
        if e.code not in quiet:
            st.error(friendly_error(e))
        return None


def header(title: str, caption: str | None = None) -> None:
    st.title(title)
    if caption:
        st.caption(caption)
