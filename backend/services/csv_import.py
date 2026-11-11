"""Vendor-record CSV import. Columns: vendor_code,name,tax_id,bank_account,bank_name. Row errors never abort the whole file."""
from __future__ import annotations

import csv
import io
import re

from backend.core.constants import BANK_ACCOUNT_REGEX, TAX_ID_REGEX

REQUIRED = ("vendor_code", "name")
COLUMNS = ("vendor_code", "name", "tax_id", "bank_account", "bank_name")
MAX_ROWS = 2000


def parse_vendor_csv(text: str) -> tuple[list[dict], list[dict]]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not set(REQUIRED) <= {f.strip() for f in reader.fieldnames}:
        return [], [{"row": 1, "error": f"header must include {', '.join(REQUIRED)}"}]
    rows, errors, seen = [], [], set()
    for n, raw in enumerate(reader, start=2):
        if n - 1 > MAX_ROWS:
            errors.append({"row": n, "error": f"file truncated at {MAX_ROWS} rows"})
            break
        r = {k: (raw.get(k) or "").strip() for k in COLUMNS}
        problems = []
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", r["vendor_code"]):
            problems.append("vendor_code must be 1-20 letters, digits, - or _")
        if not r["name"] or len(r["name"]) > 200:
            problems.append("name is required (max 200 characters)")
        if r["tax_id"] and not re.fullmatch(TAX_ID_REGEX, r["tax_id"]):
            problems.append("tax_id format invalid")
        if r["bank_account"] and not re.fullmatch(BANK_ACCOUNT_REGEX, r["bank_account"]):
            problems.append("bank_account format invalid")
        if r["vendor_code"] in seen:
            problems.append("duplicate vendor_code in file")
        if problems:
            errors.append({"row": n, "error": "; ".join(problems)})
            continue
        seen.add(r["vendor_code"])
        rows.append({k: (v or None) if k not in REQUIRED else v for k, v in r.items()})
    return rows, errors
