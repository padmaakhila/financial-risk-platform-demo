"""Dependency-free HTTP wrapper around the mock cores (used by tests and as a no-install fallback).
Run:  python -m backend.integrations.mock_server erp --port 8101
      python -m backend.integrations.mock_server vendor --port 8102
The FastAPI versions with OpenAPI docs are in erp_mock_app.py and vendor_mock_app.py."""
from __future__ import annotations

import argparse
import http.server
import json
import threading


def make_server(core, host: str = "127.0.0.1", port: int = 0) -> http.server.ThreadingHTTPServer:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _run(self, method):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            except ValueError:
                return self._send(400, {"error": "invalid JSON"})
            status, data = core.handle(method, self.path.split("?")[0], dict(self.headers), body)
            self._send(status, data)

        def _send(self, status, data):
            raw = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            self._run("GET")

        def do_POST(self):
            self._run("POST")

    return http.server.ThreadingHTTPServer((host, port), Handler)


def start_in_thread(core, port: int = 0):
    srv = make_server(core, port=port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("which", choices=["erp", "vendor"])
    ap.add_argument("--port", type=int, default=0)
    a = ap.parse_args()
    if a.which == "erp":
        from backend.integrations.erp_mock_core import ErpMock
        core, port = ErpMock(), a.port or 8101
    else:
        from backend.integrations.vendor_mock_core import VendorMock
        from scripts.generate_data import build_dataset
        core, port = VendorMock.from_dataset(build_dataset(42)), a.port or 8102
    srv = make_server(core, port=port)
    print(f"mock {a.which} service on http://127.0.0.1:{srv.server_port}  (Ctrl+C to stop)")
    srv.serve_forever()
