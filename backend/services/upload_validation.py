"""Upload validation and safe storage. Every check is deterministic; nothing here trusts the client."""
from __future__ import annotations

import csv
import hashlib
import io
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

ALLOWED = {
    ".pdf": ("application/pdf",),
    ".png": ("image/png",),
    ".jpg": ("image/jpeg",), ".jpeg": ("image/jpeg",),
    ".csv": ("text/csv", "application/vnd.ms-excel", "text/plain"),  # browsers label CSV inconsistently
}
STORED_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(pdf|png|jpg|jpeg|csv)$")


class UploadError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status


@dataclass(frozen=True)
class ValidatedUpload:
    original_filename: str  # sanitised, for display only
    extension: str
    mime_type: str
    size_bytes: int
    sha256: str
    stored_filename: str  # server-generated, never derived from the client name


def sanitize_filename(name: str) -> str:
    if not name or "\x00" in name:
        raise UploadError("INVALID_FILENAME", "The file name is missing or contains illegal characters.", 400)
    base = re.split(r"[\\/]", name)[-1].strip()  # drop any directory part (path traversal)
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base)
    if not base or base in {".", ".."} or len(base) > 255:
        raise UploadError("INVALID_FILENAME", "The file name is not acceptable.", 400)
    return base


def _check_signature(ext: str, data: bytes) -> None:
    ok = {".pdf": data.startswith(b"%PDF-"), ".png": data.startswith(b"\x89PNG\r\n\x1a\n"),
          ".jpg": data.startswith(b"\xff\xd8\xff"), ".jpeg": data.startswith(b"\xff\xd8\xff")}.get(ext)
    if ext == ".csv":
        if b"\x00" in data[:4096] or data[:2] == b"MZ":
            raise UploadError("SIGNATURE_MISMATCH", "The file content is not a text CSV.", 415)
        return
    if not ok:
        raise UploadError("SIGNATURE_MISMATCH", f"The file content does not look like a real {ext[1:].upper()} file.", 415)


def validate_upload(filename: str, data: bytes, declared_mime: str | None = None, *, max_bytes: int,
                    allowed: tuple = tuple(ALLOWED)) -> ValidatedUpload:
    safe = sanitize_filename(filename)
    ext = Path(safe).suffix.lower()
    if ext not in allowed:
        raise UploadError("UNSUPPORTED_FILE_TYPE", f"File type '{ext or 'none'}' is not supported. Allowed: {', '.join(sorted(allowed))}.", 415)
    if not data:
        raise UploadError("EMPTY_FILE", "The file is empty.", 400)
    if len(data) > max_bytes:
        raise UploadError("FILE_TOO_LARGE", f"The file is larger than the {max_bytes // (1024 * 1024)} MB limit.", 413)
    mime = (declared_mime or "").split(";")[0].strip().lower()
    if mime and mime != "application/octet-stream" and mime not in ALLOWED[ext]:
        raise UploadError("MIME_MISMATCH", f"Declared type '{mime}' does not match the '{ext}' extension.", 415)
    _check_signature(ext, data)
    if ext == ".pdf" and b"%%EOF" not in data[-2048:]:
        raise UploadError("MALFORMED_FILE", "The PDF is truncated or damaged (no end-of-file marker).", 422)
    if ext == ".csv":
        try:
            text = data.decode("utf-8-sig")
            rows = list(csv.reader(io.StringIO(text)))
        except (UnicodeDecodeError, csv.Error):
            raise UploadError("MALFORMED_FILE", "The CSV is not valid UTF-8 text.", 422) from None
        if len(rows) < 2:
            raise UploadError("MALFORMED_FILE", "The CSV needs a header row and at least one data row.", 422)
    return ValidatedUpload(safe, ext, ALLOWED[ext][0], len(data), hashlib.sha256(data).hexdigest(), f"{uuid.uuid4().hex}{ext}")


def resolve_stored_path(upload_dir: Path, stored_filename: str) -> Path:
    """Map a stored name to a path, refusing anything that could escape upload_dir."""
    if not STORED_NAME_RE.match(stored_filename or ""):
        raise UploadError("INVALID_FILENAME", "Invalid stored file name.", 400)
    root = upload_dir.resolve()
    path = (root / stored_filename).resolve()
    if root not in path.parents:
        raise UploadError("INVALID_FILENAME", "Path escapes the upload directory.", 400)
    return path


def store_upload(upload_dir: Path, v: ValidatedUpload, data: bytes) -> Path:
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = resolve_stored_path(upload_dir, v.stored_filename)
    with open(path, "xb") as fh:  # 'x' = never overwrite
        fh.write(data)
    return path
