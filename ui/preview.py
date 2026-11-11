
"""Safe server-side document previews (PNG output, no HTML/JS embedding)."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Optional


def pdf_first_page_png(
    data: bytes,
    resolution: int = 80,
) -> Optional[bytes]:
    """Render the first PDF page as PNG. Return None if rendering fails."""
    if not data or not isinstance(data, bytes):
        return None

    resolution = max(40, min(int(resolution), 150))

    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if not pdf.pages:
                return None

            image = pdf.pages[0].to_image(resolution=resolution)

            output = io.BytesIO()
            image.original.save(output, format="PNG")
            return output.getvalue()

    except Exception:
        return None


def pdf_page_count(data: bytes) -> Optional[int]:
    """Return the number of PDF pages, or None if the PDF cannot be read."""
    if not data or not isinstance(data, bytes):
        return None

    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return len(pdf.pages)

    except Exception:
        return None


def preview_kind(filename: str) -> str:
    """Identify the supported preview type from a filename extension."""
    extension = Path(str(filename or "")).suffix.lower().lstrip(".")

    return {
        "pdf": "pdf",
        "png": "image",
        "jpg": "image",
        "jpeg": "image",
        "csv": "csv",
    }.get(extension, "other")
