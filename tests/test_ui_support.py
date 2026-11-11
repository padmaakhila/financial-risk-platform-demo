import http.server
import json
import threading

import pytest

from backend.services.doc_text import invoice_lines_text
from scripts.generate_data import build_dataset
from scripts.generate_documents import write_digital_pdf
from ui.api_client import ApiClient, ApiProblem, Unauthorized, Unreachable, encode_multipart
from ui.format import (confidence_label, confidence_level, explanation_banner, find_source_snippets, friendly_error, group_exceptions, human_seconds, money,
                       percent, severity_label, status_label)
from ui.preview import pdf_first_page_png, pdf_page_count, preview_kind

SEEN = {}


class FakeApi(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self, status, obj=None, raw=None, ctype="application/json", extra=None):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _record(self, body=b""):
        SEEN.update({"path": self.path, "auth": self.headers.get("Authorization"), "ctype": self.headers.get("Content-Type"), "body": body})

    def do_GET(self):
        self._record()
        if self.path.startswith("/api/ok"):
            return self._reply(200, {"hello": "world"})
        if self.path.startswith("/api/forbidden"):
            return self._reply(403, {"error": {"code": "FORBIDDEN", "message": "no", "request_id": "r1"}})
        if self.path.startswith("/api/expired"):
            return self._reply(401, {"error": {"code": "INVALID_TOKEN", "message": "expired", "request_id": "r2"}})
        if self.path.startswith("/api/html"):
            return self._reply(502, raw=b"<html>Bad gateway</html>", ctype="text/html")
        if self.path.startswith("/api/file"):
            return self._reply(200, raw=b"%PDF-bytes", ctype="application/pdf", extra={"Content-Disposition": 'inline; filename="inv.pdf"'})
        self._reply(404, {"error": {"code": "NOT_FOUND", "message": "missing"}})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._record(body)
        if self.path == "/api/auth/login":
            return self._reply(200, {"access_token": "tok-123", "username": "u", "role": "reviewer", "expires_in": 60})
        self._reply(202, {"received": len(body)})


@pytest.fixture
def base():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def serve():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


# ---------------------------------------------------------------- client
def test_client_sends_bearer_token_and_drops_empty_params():
    srv, url = serve()
    try:
        c = ApiClient(url, token="abc")
        assert c.get("/api/ok", q="x", status=None, empty="") == {"hello": "world"}
        assert SEEN["auth"] == "Bearer abc" and SEEN["path"] == "/api/ok?q=x"
        assert ApiClient(url).get("/api/ok") and SEEN["auth"] is None
    finally:
        srv.shutdown()


def test_login_does_not_send_a_stale_token_and_returns_the_token_info():
    srv, url = serve()
    try:
        c = ApiClient(url, token="stale")
        assert c.login("u", "p")["access_token"] == "tok-123" and SEEN["auth"] is None and c.token == "stale"
        assert json.loads(SEEN["body"]) == {"username": "u", "password": "p"}
    finally:
        srv.shutdown()


def test_error_envelope_is_turned_into_typed_exceptions():
    srv, url = serve()
    try:
        c = ApiClient(url, token="t")
        with pytest.raises(ApiProblem) as e:
            c.get("/api/forbidden")
        assert (e.value.status, e.value.code, e.value.request_id) == (403, "FORBIDDEN", "r1") and not isinstance(e.value, Unauthorized)
        with pytest.raises(Unauthorized):
            c.get("/api/expired")
        with pytest.raises(ApiProblem) as e:
            c.get("/api/html")
        assert e.value.code == "HTTP_ERROR" and "502" in e.value.message and "html" not in e.value.message.lower()
    finally:
        srv.shutdown()


def test_unreachable_api_gives_a_helpful_message():
    with pytest.raises(Unreachable) as e:
        ApiClient("http://127.0.0.1:9", timeout=0.5).get("/api/ok")
    assert "uvicorn" in e.value.message and e.value.status == 0


def test_upload_builds_a_valid_multipart_request_and_downloads_return_bytes_and_name():
    srv, url = serve()
    try:
        c = ApiClient(url, token="t")
        assert c.upload("/api/documents", 'we"ird\r\nname.pdf', b"%PDF-1.4 data", "application/pdf") == {"received": SEEN["body"].__len__()}
        assert SEEN["ctype"].startswith("multipart/form-data; boundary=") and b'filename="we_ird__name.pdf"' in SEEN["body"] and b"%PDF-1.4 data" in SEEN["body"]
        data, ctype, name = c.get_bytes("/api/file")
        assert data == b"%PDF-bytes" and ctype == "application/pdf" and name == "inv.pdf"
    finally:
        srv.shutdown()


def test_encode_multipart_boundaries_are_unique():
    assert encode_multipart("file", "a", b"x", "text/plain")[1] != encode_multipart("file", "a", b"x", "text/plain")[1]


# ---------------------------------------------------------------- formatting
def test_money_confidence_and_labels():
    assert money("1234.5", "USD") == "USD 1,234.50" and money(None) == "—" and money("abc") == "abc"
    assert confidence_label(1.0, "pdf_text") == "100% (text layer)" and confidence_label(0.634, "ocr_word_conf") == "63% (OCR)"
    assert confidence_label(None, "llm_estimate").startswith("not measured") and confidence_label(None, "none") == "missing"
    assert confidence_level(0.9) == "ok" and confidence_level(0.5) == "low" and confidence_level(None) == "unknown"
    assert severity_label("critical").startswith("🟥") and status_label("AWAITING_REVIEW") == "🕒 Awaiting review" and status_label("X") == "X"
    assert human_seconds(0.25) == "250 ms" and human_seconds(3.14159) == "3.1 s" and percent(0.125) == "12.5%" and percent(None) == "—"


def test_exceptions_are_grouped_and_sorted_by_severity():
    groups = group_exceptions([{"rule_id": "ARITH_TAX", "severity": "low"}, {"rule_id": "ARITH_GRAND_TOTAL", "severity": "critical"},
                               {"rule_id": "DUP_EXACT", "severity": "high"}, {"rule_id": "XYZ_1", "severity": "info"}])
    assert list(groups) == ["Arithmetic", "Duplicates", "Other"] and groups["Arithmetic"][0]["rule_id"] == "ARITH_GRAND_TOTAL"


def test_findings_link_back_to_source_snippets():
    fields = [{"name": "grand_total", "snippet": "Grand total: 10.00", "page": 1}, {"name": "line_2", "snippet": "2 Chair 4 ...", "page": 1}, {"name": "currency", "snippet": None, "page": None}]
    assert find_source_snippets({"evidence": {"field": "grand_total"}}, fields)[0]["page"] == 1
    assert find_source_snippets({"evidence": {"line_no": 2, "field": "lines[2].line_total"}}, fields)[0]["name"] == "line_2"
    assert find_source_snippets({"evidence": {"field": "currency"}}, fields) == [] and find_source_snippets({}, fields) == []


def test_friendly_errors_never_leak_internals():
    p = lambda code, msg="server text", rid="abc123", **kw: ApiProblem(400, code, msg, rid, kw.get("details"))
    assert "recorded human approval" in friendly_error(p("APPROVAL_REQUIRED"))
    assert "abc123" in friendly_error(p("INTERNAL_ERROR")) and "Traceback" not in friendly_error(p("INTERNAL_ERROR"))
    assert friendly_error(Unauthorized(401, "INVALID_TOKEN", "x")).startswith("Your session has ended")
    assert friendly_error(p("INVALID_REQUEST", details=[{"field": "decision", "problem": "literal_error"}])) == "Please check: decision (literal_error)"
    assert friendly_error(p("UNSUPPORTED_FILE_TYPE", "Type .exe is not supported")).startswith("File not accepted")
    assert friendly_error(p("SOMETHING_NEW", "odd")) == "odd (reference abc123)"


def test_explanation_banner_distinguishes_model_from_template():
    assert explanation_banner("model")[0] == "success" and explanation_banner("template")[0] == "warning" and explanation_banner(None)[0] == "info"


# ---------------------------------------------------------------- previews
def test_pdf_preview_renders_png_and_bad_input_returns_none(tmp_path):
    p = tmp_path / "a.pdf"
    write_digital_pdf(p, invoice_lines_text(build_dataset(42)["invoices"][0]))
    png = pdf_first_page_png(p.read_bytes())
    assert png.startswith(b"\x89PNG") and pdf_page_count(p.read_bytes()) == 1
    assert pdf_first_page_png(b"not a pdf") is None and pdf_page_count(b"") is None
    assert [preview_kind(n) for n in ("a.PDF", "b.png", "c.jpeg", "d.csv", "e.exe", "noext")] == ["pdf", "image", "image", "csv", "other", "other"]
