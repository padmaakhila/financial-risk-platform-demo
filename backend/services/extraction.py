"""Extraction Agent core: read a document, measure confidence, parse fields, validate the schema.

Allowed tools: pdfplumber (text layer), Tesseract via pytesseract (scans), the rule parsers below,
Pydantic validation, and an OPTIONAL injected LLM mapper whose answers are accepted only if the value
literally appears in the source text. The LLM never receives a database handle.
Confidence: 1.0 for a PDF text layer ("pdf_text"); mean Tesseract word confidence for OCR ("ocr_word_conf").
LLM-supplied fields carry NO numeric confidence ("llm_estimate" is not a calibrated probability)."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Callable

from backend.core.money import parse_decimal
from backend.services.rules import Finding, make_finding

log = logging.getLogger("extraction")


@dataclass(frozen=True)
class Thresholds:
    low_confidence: float = 0.70
    unreadable: float = 0.40
    min_words: int = 15
    max_pages: int = 10
    max_pixels: int = 40_000_000


@dataclass
class TextLine:
    page: int
    text: str
    confidence: float | None
    method: str
    bbox: tuple | None = None
    words: int = 0


@dataclass
class FieldValue:
    name: str
    value_text: str | None
    confidence: float | None
    method: str
    page: int | None = None
    snippet: str | None = None
    bbox: tuple | None = None
    low_confidence: bool = False


@dataclass
class ExtractionResult:
    status: str = "failed"  # ok | needs_manual_entry | failed
    reason: str | None = None
    message: str | None = None
    doc_type: str = "unknown"
    document_kind: str | None = None
    mean_confidence: float | None = None
    fields: list[FieldValue] = field(default_factory=list)
    data: dict | None = None
    findings: list[Finding] = field(default_factory=list)
    attempts: list[dict] = field(default_factory=list)
    classification: dict = field(default_factory=dict)
    rejected_llm_values: list[str] = field(default_factory=list)
    schema_errors: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------- OCR engine
class TesseractEngine:
    name = "tesseract"
    PROFILES = {"default": "--oem 3 --psm 6", "alt": "--oem 3 --psm 4"}

    def __init__(self, cmd: str = ""):
        self._cmd = cmd

    def available(self) -> bool:
        try:
            import pytesseract
            if self._cmd:
                pytesseract.pytesseract.tesseract_cmd = self._cmd
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def read(self, image, profile: str, page: int) -> list[TextLine]:
        import pytesseract
        from PIL import ImageOps
        img, scale = image.convert("L"), 1.0
        if profile == "alt":  # alternative configuration: contrast stretch + upscale + different page segmentation
            img = ImageOps.autocontrast(img)
            scale = 1.5
            img = img.resize((int(img.width * scale), int(img.height * scale)))
        data = pytesseract.image_to_data(img, config=self.PROFILES[profile], output_type=pytesseract.Output.DICT, timeout=60)
        groups: dict[tuple, list] = {}
        for i, txt in enumerate(data["text"]):
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                continue
            if conf < 0 or not txt.strip():
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            groups.setdefault(key, []).append((txt, conf, data["left"][i], data["top"][i], data["width"][i], data["height"][i]))
        lines = []
        for words in groups.values():
            x0, y0 = min(w[2] for w in words), min(w[3] for w in words)
            x1, y1 = max(w[2] + w[4] for w in words), max(w[3] + w[5] for w in words)
            lines.append(TextLine(page, " ".join(w[0] for w in words), sum(w[1] for w in words) / len(words) / 100.0,
                                  "ocr_word_conf", tuple(round(v / scale) for v in (x0, y0, x1, y1)), len(words)))
        lines.sort(key=lambda l: (l.bbox[1], l.bbox[0]))
        return lines


# ---------------------------------------------------------------- parsing helpers
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ROW_INVOICE = re.compile(r"^(\d{1,3})\s+(.+?)\s+(\d+(?:\.\d+)?)\s+(\d+\.\d{2})\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+\.\d{2})\s+(\d+\.\d{2})$")
ROW_PO = re.compile(r"^(\d{1,3})\s+(.+?)\s+(\d+(?:\.\d+)?)\s+(\d+\.\d{2})\s+(\d+(?:\.\d+)?)$")
ROW_GRN = re.compile(r"^(\d{1,3})\s+(.+?)\s+(\d+(?:\.\d+)?)$")


def _match_line(lines: list[TextLine], pattern: str):
    rx = re.compile(pattern, re.I)
    for ln in lines:
        m = rx.match(ln.text.strip())
        if m:
            return m, ln
    return None, None


def _fv(name, ln: TextLine | None, value: str | None, th: Thresholds, note_method: str | None = None) -> FieldValue:
    if ln is None:
        return FieldValue(name, None, None, "none")
    low = ln.confidence is not None and ln.confidence < th.low_confidence
    return FieldValue(name, value, ln.confidence, note_method or ln.method, ln.page, ln.text[:300], ln.bbox, low)


def _to_date(s: str | None):
    s = (s or "").strip()
    if not s:
        return None
    if _DATE_RE.match(s):
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    return None


def _to_dec(s: str | None):
    try:
        return parse_decimal(s) if (s or "").strip() else None
    except ValueError:
        return None
def parse_invoice(
    lines: list[TextLine],
    th: Thresholds,
) -> tuple[dict, list[FieldValue]]:
    """Parse invoice fields from common label formats."""
    data: dict = {}
    fields: list[FieldValue] = []
    full_text = "\n".join(ln.text.strip() for ln in lines if ln.text.strip())

    stop_labels = (
        r"Invoice\s*(?:Number|No\.?|ID|#)|"
        r"Vendor(?:\s*Name)?|"
        r"Tax\s*ID|GSTIN|GST\s*Number|"
        r"Bank(?:\s*Account)?|Account\s*(?:Number|No\.?)|"
        r"Invoice\s*Date|Due\s*Date|"
        r"Currency(?:\s*Code)?|"
        r"Subtotal|"
        r"Tax\s*(?:Total|Amount)|Total\s*Tax|GST\s*Amount|"
        r"Tax\s*\(\s*\d+(?:\.\d+)?%\s*\)|"
        r"Grand\s*Total|Total\s*Amount|Invoice\s*Total|"
        r"Printed\s*Invoice\s*Total|Amount\s*Due|"
        r"PO(?:\s*(?:Number|No\.?|ID))?|"
        r"GRN(?:\s*(?:Number|No\.?|ID))?|"
        r"Notes"
    )

    def find_field(name: str, labels: str, converter=None):
        pattern = re.compile(
            rf"(?:{labels})\s*[:#-]?\s*(.*?)"
            rf"(?=\s+(?:{stop_labels})\s*[:#-]?\s*|$)",
            re.IGNORECASE,
        )
        match = pattern.search(full_text)
        raw = match.group(1).strip(" \t:-") if match else None

        if name == "bank_account_raw" and raw:
            account_match = re.search(
                r"\bFB\d{2}[A-Z]{4}\d{10}\b",
                raw.upper()
            )
            raw = account_match.group(0) if account_match else None

        source_line = None
        if match:
            label_match = re.search(
                rf"(?:{labels})",
                match.group(0),
                re.IGNORECASE,
            )
            if label_match:
                absolute_label_start = match.start() + label_match.start()
                for ln in lines:
                    line_start = full_text.find(ln.text.strip())
                    if (
                        ln.text.strip()
                        and line_start >= 0
                        and line_start <= absolute_label_start
                        < line_start + len(ln.text.strip())
                    ):
                        source_line = ln
                        break

            if source_line is None:
                source_line = next(
                    (
                        ln for ln in lines
                        if re.search(rf"(?:{labels})", ln.text, re.IGNORECASE)
                    ),
                    None,
                )

        value = converter(raw) if raw and converter else raw
        data[name] = value

        field = _fv(name, source_line, raw, th)
        if raw and value is None:
            field.low_confidence = True
            field.confidence = 0.0
        if source_line is not None and not raw:
            field.value_text = None
            field.method = "none"
            field.confidence = None
            field.low_confidence = False

        fields.append(field)

    invoice_heading = re.compile(
        r"^\s*INVOICE\s+([A-Z0-9][A-Z0-9/-]*)\s*$",
        re.IGNORECASE,
    )

    heading_match = next(
        (
            (match, ln)
            for ln in lines
            if (match := invoice_heading.match(ln.text.strip()))
        ),
        (None, None),
    )

    if heading_match[0]:
        invoice_number = heading_match[0].group(1)
        data["invoice_number"] = invoice_number
        fields.append(_fv("invoice_number", heading_match[1], invoice_number, th))
    else:
        find_field("invoice_number", r"Invoice\s*(?:Number|No\.?|ID|#)")
    find_field("vendor_name_raw", r"Vendor(?:\s*Name)?")
    find_field("vendor_tax_id_raw", r"(?:Tax\s*ID|GSTIN|GST\s*Number)")
    find_field(
        "bank_account_raw",
        r"(?:Bank(?:\s*Account)?|Account\s*(?:Number|No\.?))",
    )
    find_field("invoice_date", r"Invoice\s*Date", _to_date)
    find_field("due_date", r"Due\s*Date", _to_date)

    # Capture currency either from a Currency label or from an amount such as "INR 54000.00".
    currency_match = re.search(
        r"\b(INR|USD|EUR|GBP|CAD|AUD)\b",
        full_text,
        re.IGNORECASE,
    )
    currency = currency_match.group(1).upper() if currency_match else None
    data["currency"] = currency
    currency_line = next(
        (
            ln for ln in lines
            if currency and re.search(rf"\b{currency}\b", ln.text, re.IGNORECASE)
        ),
        None,
    )
    fields.append(_fv("currency", currency_line, currency, th))

    # Capture numeric amounts with an optional currency code before or after the number.
    amount = r"(?:(?:INR|USD|EUR|GBP|CAD|AUD)\s*)?([0-9][0-9,]*(?:\.\d{1,2})?)(?:\s*(?:INR|USD|EUR|GBP|CAD|AUD))?"

    def find_amount(name: str, labels: str):
        pattern = re.compile(
            rf"(?:{labels})\s*[:#-]?\s*{amount}",
            re.IGNORECASE,
        )
        match = pattern.search(full_text)
        raw = match.group(1).replace(",", "") if match else None
        value = _to_dec(raw) if raw else None
        data[name] = value

        source_line = None
        if match:
            label_match = re.search(rf"(?:{labels})", match.group(0), re.IGNORECASE)
            if label_match:
                start = match.start() + label_match.start()
                for ln in lines:
                    line_start = full_text.find(ln.text.strip())
                    if (
                        ln.text.strip()
                        and line_start >= 0
                        and line_start <= start < line_start + len(ln.text.strip())
                    ):
                        source_line = ln
                        break

        field = _fv(name, source_line, raw, th)
        if raw and value is None:
            field.low_confidence = True
            field.confidence = 0.0
        fields.append(field)

    find_amount("subtotal", r"Subtotal")
    find_amount(
        "tax_total",
        r"(?:\bTax\s*(?:Total|Amount)\b|\bGST\s*Amount\b|\bTax\s*\(\s*\d+(?:\.\d+)?%\s*\))",
    )
    find_amount(
        "grand_total",
        r"(?:Grand\s*Total|Total\s*Amount|Invoice\s*Total|"
        r"Printed\s*Invoice\s*Total|Amount\s*Due)",
    )

    notes_match = None
    notes_line = None

    for ln in lines:
        candidate = re.match(
            r"^\s*Notes\s*:\s*(.*)$",
            ln.text.strip(),
            re.IGNORECASE,
        )
        if candidate:
            notes_match = candidate
            notes_line = ln
            break

    notes_raw = notes_match.group(1) if notes_match else None
    data["notes"] = notes_raw
    fields.append(_fv("notes", notes_line, notes_raw, th))
    po_match = re.search(
        r"\bPO(?:\s*(?:Number|No\.?|ID))?\s*[:#-]?\s*([A-Z0-9-]+)",
        full_text,
        re.IGNORECASE,
    )
    grn_match = re.search(
        r"\bGRN(?:\s*(?:Number|No\.?|ID))?\s*[:#-]?\s*([A-Z0-9-]+)",
        full_text,
        re.IGNORECASE,
    )

    data["po_number"] = po_match.group(1) if po_match else None
    data["grn_number"] = grn_match.group(1) if grn_match else None

    po_line = next(
        (ln for ln in lines if re.search(r"\b(?:PO|GRN)\b", ln.text, re.IGNORECASE)),
        None,
    )
    fields.append(_fv("po_number", po_line, data["po_number"], th))
    fields.append(_fv("grn_number", po_line, data["grn_number"], th))

    items = []
    for ln in lines:
        match = ROW_INVOICE.match(ln.text.strip())
        if match:
            n, desc, qty, unit, disc, taxpct, total, tax = match.groups()
            items.append({
                "line_no": int(n),
                "description": desc.strip(),
                "quantity": Decimal(qty),
                "unit_price": Decimal(unit),
                "discount_pct": Decimal(disc),
                "tax_rate": Decimal(taxpct) / 100,
                "line_total": Decimal(total),
                "tax_amount": Decimal(tax),
            })
            fields.append(_fv(f"line_{n}", ln, ln.text.strip(), th))

    data["lines"] = items
    return data, fields

def parse_po(lines: list[TextLine], th: Thresholds):
    data, fields = {}, []

    header_patterns = [
        (
            "po_number",
            r"(?i)^(?:PURCHASE\s+ORDER(?:\s+(?:NO\.?|NUMBER))?\s*[:#]?\s*|PO\s+(?:NO\.?|NUMBER)\s*[:#]?\s*|PO\s*:\s*)(\S+)",
            None,
        ),
        (
            "vendor_code",
            r"(?i)^(?:Vendor\s+code|Vendor\s+ID|Supplier\s+code)\s*:\s*(\S+)",
            None,
        ),
        (
            "order_date",
            r"(?i)^(?:Order\s+date|PO\s+date|Date)\s*:\s*(.+)$",
            _to_date,
        ),
        (
            "currency",
            r"(?i)^(?:Currency|Currency\s+code)\s*:\s*([A-Z]{3})\b",
            str.upper,
        ),
    ]

    for name, pattern, converter in header_patterns:
        match, source_line = _match_line(lines, pattern)
        raw = match.group(1).strip() if match else None

        try:
            data[name] = converter(raw) if converter and raw else raw
        except (ValueError, TypeError):
            data[name] = None

        fields.append(_fv(name, source_line, raw, th))

    # Preserve the existing PO line-item extraction.
    data["lines"] = []

    for ln in lines:
        match = ROW_PO.match(ln.text.strip())

        if match:
            n, description, quantity, price, tax = match.groups()

            data["lines"].append({
                "line_no": int(n),
                "description": description.strip(),
                "quantity": Decimal(quantity),
                "unit_price": Decimal(price),
                "tax_rate": Decimal(tax) / 100,
            })

            fields.append(_fv(f"line_{n}", ln, ln.text.strip(), th))

    return data, fields

def parse_grn(lines: list[TextLine], th: Thresholds):
    data, fields = {}, []
    for name, pat, conv in [("grn_number", r"^GOODS RECEIVED NOTE\s+(\S+)", None), ("po_number", r"^PO reference:\s*(\S+)", None),
                            ("receipt_date", r"^Receipt date:\s*(.*)$", _to_date)]:
        m, ln = _match_line(lines, pat)
        raw = m.group(1).strip() if m else None
        data[name] = conv(raw) if (conv and raw) else raw
        fields.append(_fv(name, ln, raw, th))
    data["lines"] = []
    for ln in lines:
        if re.match(r"^(PO|Receipt|GOODS)", ln.text.strip(), re.I):
            continue
        m = ROW_GRN.match(ln.text.strip())
        if m:
            n, d, q = m.groups()
            data["lines"].append({"po_line_no": int(n), "description": d.strip(), "quantity_received": Decimal(q)})
            fields.append(_fv(f"line_{n}", ln, ln.text.strip(), th))
    return data, fields


def parse_vendor(lines: list[TextLine], th: Thresholds):
    data, fields = {}, []
    for name, pat in [("vendor_code", r"^Vendor code:\s*(\S+)"), ("name", r"^Vendor name:\s*(.+)$"), ("tax_id", r"^Tax ID:\s*(\S+)"),
                      ("bank_account", r"^Bank account:\s*(\S+)"), ("bank_name", r"^Bank name:\s*(.+)$")]:
        m, ln = _match_line(lines, pat)
        data[name] = m.group(1).strip() if m else None
        fields.append(_fv(name, ln, data[name], th))
    return data, fields


PARSERS = {"invoice": parse_invoice, "purchase_order": parse_po, "goods_receipt": parse_grn, "vendor_record": parse_vendor}
LLM_FILLABLE = ("invoice_number", "vendor_name_raw", "grand_total", "invoice_date")


def _apply_llm(data, fields, lines, llm_extract, result: ExtractionResult):
    """Fill gaps with an LLM mapping, but only with values that literally occur in the source text."""
    missing = [f for f in LLM_FILLABLE if data.get(f) in (None, "")]
    if not missing or llm_extract is None:
        return
    source = "\n".join(l.text for l in lines)
    try:
        proposed = llm_extract(source, missing) or {}
    except Exception as exc:  # LLM failure must never break extraction
        log.warning("llm_extract failed: %s", type(exc).__name__)
        return
    for name in missing:
        raw = proposed.get(name)
        if not isinstance(raw, str) or not raw.strip() or raw.strip().casefold() not in source.casefold():
            if raw:
                result.rejected_llm_values.append(name)
            continue
        value = {"grand_total": _to_dec, "invoice_date": _to_date}.get(name, lambda s: s.strip())(raw)
        if value is None:
            result.rejected_llm_values.append(name)
            continue
        data[name] = value
        snippet = next((l for l in lines if raw.strip().casefold() in l.text.casefold()), None)
        for f in fields:
            if f.name == name:
                f.value_text, f.method, f.confidence = raw.strip(), "llm_estimate", None
                f.page, f.snippet, f.low_confidence = (snippet.page, snippet.text[:300], True) if snippet else (None, None, True)


# ---------------------------------------------------------------- reading documents
def _ocr_pages(engine, images, profile) -> list[TextLine]:
    out = []
    for n, img in enumerate(images, 1):
        out += engine.read(img, profile, n)
    return out


def _stats(lines: list[TextLine]) -> tuple[float, int]:
    words = sum(l.words for l in lines)
    return (sum((l.confidence or 0) * l.words for l in lines) / words if words else 0.0), words


def _read_scanned(images, engine, th: Thresholds, result: ExtractionResult) -> list[TextLine] | None:
    best, best_score = None, -1.0
    for profile in ("default", "alt"):  # at most ONE retry, with the alternative configuration
        try:
            lines = _ocr_pages(engine, images, profile)
        except Exception as exc:
            result.attempts.append({"profile": profile, "error": type(exc).__name__})
            continue
        mean, words = _stats(lines)
        result.attempts.append({"profile": profile, "mean_confidence": round(mean, 3), "words": words})
        if mean * min(words, 200) > best_score:
            best, best_score = lines, mean * min(words, 200)
        if mean >= th.low_confidence and words >= th.min_words:
            break
    return best


def extract_document(path: Path | str, *, engine=None, llm_extract: Callable | None = None, thresholds: Thresholds | None = None,
                     validator: Callable | None = None, classify_fn: Callable | None = None, tesseract_cmd: str = "") -> ExtractionResult:
    """Never raises for bad input: returns a result with status ok / needs_manual_entry / failed."""
    th = thresholds or Thresholds()
    result = ExtractionResult()
    path = Path(path)
    try:
        return _extract(path, engine, llm_extract, th, validator, classify_fn, tesseract_cmd, result)
    except Exception as exc:  # last-resort guard: unreadable or hostile files must not crash the worker
        log.exception("extraction failed for %s", path.name)
        result.status, result.reason = "failed", type(exc).__name__
        result.message = "The document could not be processed automatically. Please enter the data manually."
        return result


def _extract(path, engine, llm_extract, th, validator, classify_fn, tesseract_cmd, result):
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = th.max_pixels
    ext = path.suffix.lower()
    images, lines = [], []
    if not path.is_file():
        result.status, result.reason, result.message = "failed", "FILE_NOT_FOUND", "The stored file could not be found."
        return result
    if ext == ".pdf":
        import pdfplumber
        try:
            pdf = pdfplumber.open(path)
        except Exception:
            result.status, result.reason, result.message = "needs_manual_entry", "MALFORMED_PDF", "The PDF could not be opened."
            return result
        with pdf:
            pages = pdf.pages[: th.max_pages]
            for n, page in enumerate(pages, 1):
                for ln in page.extract_text_lines():
                    if ln["text"].strip():
                        lines.append(TextLine(n, ln["text"].strip(), 1.0, "pdf_text", (ln["x0"], ln["top"], ln["x1"], ln["bottom"]),
                                              len(ln["text"].split())))
            scanned = sum(len(l.text) for l in lines) < 30
            if scanned:
                images = [p.to_image(resolution=200).original for p in pages]
    elif ext in (".png", ".jpg", ".jpeg"):
        scanned, images = True, [Image.open(path)]
    else:
        result.status, result.reason, result.message = "failed", "UNSUPPORTED_FOR_EXTRACTION", f"{ext} files are not extracted."
        return result

    if scanned:
        engine = engine or TesseractEngine(tesseract_cmd)
        if not engine.available():
            result.status, result.reason = "needs_manual_entry", "OCR_UNAVAILABLE"
            result.message = "Tesseract OCR is not installed, so scanned documents need manual entry. See README for installation."
            result.document_kind = "scanned_unreadable"
            return result
        lines = _read_scanned(images, engine, th, result) or []
        mean, words = _stats(lines)
        kind = "scanned_unreadable" if (mean < th.unreadable or words < th.min_words) else (
            "scanned_low_quality" if mean < th.low_confidence else "scanned_good")
    else:
        mean, words, kind = 1.0, sum(l.words for l in lines), "digital_pdf"
    result.document_kind, result.mean_confidence = kind, round(mean, 4)

    if kind == "scanned_unreadable":
        result.findings.append(make_finding("DOC_UNREADABLE", "The scanned document could not be read reliably",
                                            expected=f"mean OCR confidence >= {th.unreadable}", actual=f"{mean:.2f} over {words} words",
                                            evidence={"attempts": result.attempts}))
        result.status, result.reason = "needs_manual_entry", "UNREADABLE_SCAN"
        result.message = "The scan is too unclear to read. Please enter the data manually or upload a better scan."
        return result
    if kind == "scanned_low_quality":
        result.findings.append(make_finding("DOC_LOW_CONF", "OCR confidence is low; verify extracted values against the original",
                                            expected=f"mean OCR confidence >= {th.low_confidence}", actual=f"{mean:.2f}",
                                            evidence={"attempts": result.attempts, "method": "ocr_word_conf"}))

    text = "\n".join(l.text for l in lines)
    result.classification = (classify_fn or _default_classify)(text)
    doc_type = result.classification["label"]
    result.doc_type = doc_type
    if doc_type not in PARSERS:
        result.status, result.reason, result.message = "needs_manual_entry", "UNKNOWN_DOCUMENT_TYPE", "The document type could not be determined."
        return result
    data, fields = PARSERS[doc_type](lines, th)
    if doc_type == "invoice":
        _apply_llm(data, fields, lines, llm_extract, result)
        if data.get("grand_total") is None and not data["lines"]:
            result.fields, result.data = fields, data
            result.status, result.reason, result.message = "needs_manual_entry", "REQUIRED_FIELDS_NOT_FOUND", "No totals or line items were found."
            return result
    result.fields = fields
    validator = validator or _default_validator
    try:
        result.data = validator(doc_type, data)
    except Exception as exc:
        from backend.schemas.extraction import ValidationError, safe_errors
        if isinstance(exc, ValidationError):
            result.schema_errors = safe_errors(exc)
            result.data = data
            result.status, result.reason, result.message = "needs_manual_entry", "SCHEMA_VALIDATION_FAILED", "Extracted values failed validation."
            return result
        raise
    result.status = "ok"
    return result


def _default_validator(doc_type, data):
    from backend.schemas.extraction import validate_structured
    return validate_structured(doc_type, data)


def _default_classify(text):
    from backend.services.classifier import classify
    return classify(text)
