# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import io

from fastapi import HTTPException


def decode_text(raw_bytes: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=400, detail="Unable to decode uploaded file.")


def extract_text_content(raw_bytes: bytes) -> str:
    return decode_text(raw_bytes).strip()


def extract_csv_content(raw_bytes: bytes) -> str:
    content = decode_text(raw_bytes)
    reader = csv.reader(io.StringIO(content))
    return "\n".join(
        ", ".join(cell.strip() for cell in row if cell and cell.strip())
        for row in reader
        if any(cell and cell.strip() for cell in row)
    ).strip()