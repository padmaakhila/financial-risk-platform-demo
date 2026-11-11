"""HTTP client the Streamlit pages use to talk to the FastAPI backend (standard library only).
The UI never touches the database and never applies business rules; it only calls this client."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid


class ApiProblem(Exception):
    def __init__(self, status: int, code: str, message: str, request_id: str | None = None, details=None):
        super().__init__(message)
        self.status, self.code, self.message, self.request_id, self.details = status, code, message, request_id, details


class Unauthorized(ApiProblem):
    """401: no/expired/revoked token. The UI clears the session and asks the user to sign in again."""


class Unreachable(ApiProblem):
    """The API could not be contacted at all (not started, wrong URL, timeout)."""


def encode_multipart(field: str, filename: str, data: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    safe = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{safe}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n").encode()
    return head + data + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


class ApiClient:
    def __init__(self, base_url: str, token: str | None = None, timeout: float = 75.0):
        self.base_url, self.token, self.timeout = base_url.rstrip("/"), token, timeout

    # ---- low level
    def _do(self, method: str, path: str, *, params=None, body: bytes | None = None, content_type: str | None = None):
        url = self.base_url + path
        if params:
            q = {k: v for k, v in params.items() if v not in (None, "")}
            if q:
                url += "?" + urllib.parse.urlencode(q)
        headers = {"Accept": "application/json, */*"}
        if content_type:
            headers["Content-Type"] = content_type
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            self._raise(e.code, raw)
        except (socket.timeout, TimeoutError):
            raise Unreachable(0, "TIMEOUT", "The server took too long to answer. Please try again.") from None
        except (urllib.error.URLError, ConnectionError, OSError):
            raise Unreachable(0, "UNREACHABLE", f"Cannot reach the API at {self.base_url}. Start it with: "
                                                "uvicorn backend.main:create_app --factory --port 8000") from None

    @staticmethod
    def _raise(status: int, raw: bytes):
        try:
            err = json.loads(raw)["error"]
            code, message, rid, details = err.get("code", "ERROR"), err.get("message", "Request failed."), err.get("request_id"), err.get("details")
        except (ValueError, KeyError, TypeError):
            code, message, rid, details = "HTTP_ERROR", f"Unexpected response from the server (HTTP {status}).", None, None
        cls = Unauthorized if status == 401 else ApiProblem
        raise cls(status, code, message, rid, details)

    def _json(self, method, path, *, params=None, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        _, _, raw = self._do(method, path, params=params, body=body, content_type="application/json" if body is not None else None)
        return json.loads(raw) if raw else {}

    # ---- JSON verbs
    def get(self, path: str, **params) -> dict:
        return self._json("GET", path, params=params)

    def post(self, path: str, payload: dict | None = None, **params) -> dict:
        return self._json("POST", path, params=params, payload=payload if payload is not None else None)

    def put(self, path: str, payload: dict) -> dict:
        return self._json("PUT", path, payload=payload)

    def patch(self, path: str, payload: dict) -> dict:
        return self._json("PATCH", path, payload=payload)

    # ---- files
    def get_bytes(self, path: str, **params) -> tuple[bytes, str, str | None]:
        _, headers, raw = self._do("GET", path, params=params)
        h = {k.lower(): v for k, v in headers.items()}
        disp = h.get("content-disposition", "")
        name = disp.split("filename=")[-1].strip('" ') if "filename=" in disp else None
        return raw, h.get("content-type", "application/octet-stream"), name

    def upload(self, path: str, filename: str, data: bytes, content_type: str) -> dict:
        body, ctype = encode_multipart("file", filename, data, content_type)
        _, _, raw = self._do("POST", path, body=body, content_type=ctype)
        return json.loads(raw) if raw else {}

    # ---- auth
    def login(self, username: str, password: str) -> dict:
        saved, self.token = self.token, None
        try:
            return self.post("/api/auth/login", {"username": username, "password": password})
        finally:
            self.token = saved
