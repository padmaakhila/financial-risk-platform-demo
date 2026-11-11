"""Shared dependencies: DB session per request, authentication, permission checks."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.api.errors import ApiError
from backend.auth.permissions import can
from backend.core.security import TokenError, decode_access_token
from backend.models import User
from backend.services.audit import append_audit_event

bearer = HTTPBearer(auto_error=False, description="JWT from POST /api/auth/login")


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    role: str
    jti: str | None = None
    exp: float | None = None


def get_session(request: Request):
    """One transaction per request: commit on success, roll back on any error."""
    session = request.app.state.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer), db=Depends(get_session)) -> CurrentUser:
    if creds is None:
        raise ApiError(401, "NOT_AUTHENTICATED", "Sign in to continue.")
    try:
        claims = decode_access_token(creds.credentials)
    except TokenError:
        raise ApiError(401, "INVALID_TOKEN", "Your session has expired or is invalid. Sign in again.") from None
    if request.app.state.revoked.is_revoked(claims.get("jti")):
        raise ApiError(401, "INVALID_TOKEN", "You have signed out. Sign in again.")
    user = db.get(User, int(claims["sub"]))
    if user is None or not user.is_active:
        raise ApiError(401, "INVALID_TOKEN", "This account is not active.")
    request.state.user = user.username
    return CurrentUser(user.id, user.username, user.role, claims.get("jti"), claims.get("exp"))  # role comes from the DB, not the token


def require(permission: str):
    def dependency(request: Request, user: CurrentUser = Depends(get_current_user), db=Depends(get_session)) -> CurrentUser:
        if not can(user.role, permission):
            append_audit_event(db, actor_id=user.id, actor_label=f"user:{user.id}:{user.role}", action="ACCESS_DENIED", entity_type="api",
                               entity_id=request.url.path[:40], tool_result={"permission": permission, "method": request.method})
            db.commit()  # keep the record even though the request fails
            raise ApiError(403, "FORBIDDEN", "You do not have permission to do this.")
        return user
    return dependency


def label(user: CurrentUser) -> str:
    return f"user:{user.id}:{user.role}"
