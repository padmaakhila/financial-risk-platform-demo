"""Create sample invoice files from the synthetic dataset.
  python -m scripts.generate_documents [--limit 40]
Writes to data/documents/:  digital PDFs (ReportLab), scanned-style PDFs (Pillow image,
needs no Tesseract to *create*), unreadable / low-quality scans, unsupported files.
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from backend.core.config import BASE_DIR
from backend.services.doc_text import (grn_lines_text, invoice_lines_text, po_lines_text,
                                       vendor_lines_text)
from scripts.generate_data import build_dataset


def write_digital_pdf(path: Path, lines: list[str]) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    c.setFont("Courier", 8)
    for text in lines:
        c.drawString(40, y, text[:110])
        y -= 14
    c.save()


def write_scanned_pdf(path: Path, lines: list[str], quality: str, rng: random.Random) -> None:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    img = Image.new("L", (1240, 1754), 255)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=26)
    except TypeError:
        font = ImageFont.load_default()
    y = 60
    for text in lines:
        draw.text((60, y), text[:90], fill=0, font=font)
        y += 38
    if quality == "low":
        img = img.rotate(3, fillcolor=255).filter(ImageFilter.GaussianBlur(2.2))
    if quality == "unreadable":
        px = img.load()
        for _ in range(250000):
            px[rng.randrange(1240), rng.randrange(1754)] = rng.choice((0, 255))
        img = img.filter(ImageFilter.GaussianBlur(4))
    img.convert("RGB").save(path, "PDF", resolution=150.0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40, help="max invoices to render (all scenario kinds are always included)")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    ds = build_dataset(a.seed)
    out = BASE_DIR / "data" / "documents"
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(a.seed)
    vendors = {v["vendor_code"]: v for v in ds["vendors"]}
    picked, seen = [], {}
    for inv in ds["invoices"]:
        seen[inv["scenario_code"]] = seen.get(inv["scenario_code"], 0) + 1
        if seen[inv["scenario_code"]] <= 2 or len(picked) < a.limit // 2:
            picked.append(inv)
        if len(picked) >= a.limit + 40:
            break
    count = 0
    for inv in picked:
        lines = invoice_lines_text(inv)
        base = f"{inv['scenario_code']}_{inv['invoice_number'].replace('/', '-')}"
        kind = inv["document_kind"]
        if kind == "digital_pdf":
            write_digital_pdf(out / f"{base}.pdf", lines)
        elif kind == "scanned_good":
            write_scanned_pdf(out / f"{base}_scan.pdf", lines, "good", rng)
        elif kind == "scanned_low_quality":
            write_scanned_pdf(out / f"{base}_lowq.pdf", lines, "low", rng)
        elif kind == "scanned_unreadable":
            write_scanned_pdf(out / f"{base}_unreadable.pdf", lines, "unreadable", rng)
        count += 1
    for t in ds["ground_truth"]:
        if t["scenario_code"] == "S18_UNSUPPORTED_FILE":
            (out / t["file_name"]).write_bytes(b"MZ\x90\x00 synthetic non-invoice test content")
    print(f"Wrote {count} invoice documents + unsupported-file samples to {out}")


if __name__ == "__main__":
    main()
