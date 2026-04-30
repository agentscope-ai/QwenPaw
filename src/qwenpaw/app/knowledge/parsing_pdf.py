# -*- coding: utf-8 -*-
from __future__ import annotations

import io

from fastapi import HTTPException


def extract_pdf_text(raw_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="PDF support requires the pypdf package.") from exc

    reader = PdfReader(io.BytesIO(raw_bytes))
    return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()