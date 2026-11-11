import pytest

from backend.services.upload_validation import (UploadError, resolve_stored_path, sanitize_filename, store_upload, validate_upload)
from scripts.generate_data import build_dataset

MB = 1024 * 1024
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 50
JPG = b"\xff\xd8\xff\xe0" + b"0" * 50
CSV = b"vendor_code,name\nV1,Acme\n"


def code_of(fn, *a, **k):
    with pytest.raises(UploadError) as e:
        fn(*a, **k)
    return e.value.code, e.value.http_status


def check(name, data, mime=None, max_bytes=10 * MB):
    return validate_upload(name, data, mime, max_bytes=max_bytes)


def test_valid_files_accepted_with_server_generated_names():
    for name, data, mime in [("a.pdf", PDF, "application/pdf"), ("b.PNG", PNG, "image/png"), ("c.jpg", JPG, "image/jpeg"),
                             ("d.csv", CSV, "text/csv"), ("e.jpeg", JPG, "application/octet-stream")]:
        v = check(name, data, mime)
        assert v.stored_filename != name and len(v.sha256) == 64 and v.size_bytes == len(data)


def test_unsupported_types_from_ground_truth_are_rejected_with_415():
    names = [t["file_name"] for t in build_dataset(42)["ground_truth"] if t["scenario_code"] == "S18_UNSUPPORTED_FILE"]
    assert len(names) == 5
    for n in names:
        assert code_of(check, n, b"MZ\x90\x00 data") == ("UNSUPPORTED_FILE_TYPE", 415)


def test_double_extension_and_no_extension_rejected():
    assert code_of(check, "invoice.pdf.exe", PDF)[0] == "UNSUPPORTED_FILE_TYPE"
    assert code_of(check, "invoice", PDF)[0] == "UNSUPPORTED_FILE_TYPE"


def test_signature_must_match_extension():
    assert code_of(check, "fake.pdf", b"MZ\x90\x00 not a pdf")[0] == "SIGNATURE_MISMATCH"
    assert code_of(check, "fake.png", JPG)[0] == "SIGNATURE_MISMATCH"
    assert code_of(check, "fake.csv", b"MZ\x90\x00,a\n1,2\n")[0] == "SIGNATURE_MISMATCH"
    assert code_of(check, "bin.csv", b"a,b\n\x00\x01,2\n")[0] == "SIGNATURE_MISMATCH"


def test_empty_oversize_truncated_and_bad_csv():
    assert code_of(check, "a.pdf", b"")[0] == "EMPTY_FILE"
    assert code_of(check, "a.pdf", PDF + b"x" * 2000, max_bytes=1000) == ("FILE_TOO_LARGE", 413)
    assert code_of(check, "a.pdf", b"%PDF-1.4\n1 0 obj\n" + b"x" * 3000)[0] == "MALFORMED_FILE"
    assert code_of(check, "a.csv", b"onlyheader\n")[0] == "MALFORMED_FILE"
    assert code_of(check, "a.csv", b"a,b\n\xff\xfe\xfa,2\n")[0] == "MALFORMED_FILE"


def test_mime_must_agree_with_extension():
    assert code_of(check, "a.pdf", PDF, "image/png")[0] == "MIME_MISMATCH"
    assert code_of(check, "a.csv", CSV, "application/pdf")[0] == "MIME_MISMATCH"


def test_filename_sanitising_blocks_path_traversal_and_nulls():
    assert sanitize_filename("../../etc/passwd.pdf") == "passwd.pdf"
    assert sanitize_filename("C:\\Users\\x\\inv<>.pdf") == "inv__.pdf"
    for bad in ("", "..", "a\x00.pdf", "x" * 300):
        assert code_of(sanitize_filename, bad)[0] == "INVALID_FILENAME"


def test_stored_path_resolution_stays_inside_upload_dir(tmp_path):
    for bad in ("../x.pdf", "/etc/passwd", "..%2f..%2fx.pdf", "a.pdf", "ABC.exe", "0" * 32 + ".exe", None):
        assert code_of(resolve_stored_path, tmp_path, bad)[0] == "INVALID_FILENAME"
    good = "a" * 32 + ".pdf"
    assert resolve_stored_path(tmp_path, good).parent == tmp_path.resolve()


def test_store_upload_writes_once_and_never_overwrites(tmp_path):
    v = check("inv.pdf", PDF)
    path = store_upload(tmp_path / "uploads", v, PDF)
    assert path.read_bytes() == PDF and path.name == v.stored_filename
    with pytest.raises(FileExistsError):
        store_upload(tmp_path / "uploads", v, PDF)
