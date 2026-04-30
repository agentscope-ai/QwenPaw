# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile

from .assets import save_asset_bytes
from .parsing_chunking import (
    KnowledgeChunkModelError,
    ReActAgent,
    chunk_text,
    chunk_text_with_model,
    create_model_and_formatter,
    normalize_content_for_chunking,
)
from .parsing_docx import extract_docx_payload
from .parsing_pdf import extract_pdf_text
from .parsing_spreadsheet import extract_xls_text, extract_xlsx_text
from .parsing_text import extract_csv_content, extract_text_content


SUPPORTED_UPLOAD_SUFFIXES = {
    ".csv",
    ".docx",
    ".json",
    ".md",
    ".markdown",
    ".pdf",
    ".py",
    ".txt",
    ".xls",
    ".xlsx",
    ".yaml",
    ".yml",
}


def extract_upload_payload(
    upload: UploadFile,
    raw_bytes: bytes,
    knowledge_id: str,
    document_id: str,
    chunk_size: int = 1024,
) -> dict[str, Any]:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix or 'unknown'}.")

    assets: list[dict[str, Any]] = []
    if suffix in {".txt", ".md", ".markdown", ".json", ".py", ".yaml", ".yml"}:
        content = extract_text_content(raw_bytes)
    elif suffix == ".csv":
        content = extract_csv_content(raw_bytes)
    elif suffix == ".pdf":
        content = extract_pdf_text(raw_bytes)
    elif suffix == ".docx":
        payload = extract_docx_payload(raw_bytes, knowledge_id, document_id)
        content = payload["content"]
        assets = payload["assets"]
    elif suffix == ".xlsx":
        content = extract_xlsx_text(raw_bytes)
    elif suffix == ".xls":
        content = extract_xls_text(raw_bytes)
    else:
        content = extract_text_content(raw_bytes)

    return {
        "content": normalize_content_for_chunking(content, chunk_size),
        "assets": assets,
    }