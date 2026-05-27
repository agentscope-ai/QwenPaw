# -*- coding: utf-8 -*-
"""Desktop-only API helpers."""

import logging
import os
import webbrowser
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...tauri.env import DESKTOP_APP_ENV
from ...utils.logging import LOG_NAMESPACE

router = APIRouter(prefix="/desktop", tags=["desktop"])
logger = logging.getLogger(LOG_NAMESPACE)

SUPPORTED_EXTERNAL_SCHEMES = {"http", "https", "mailto", "tel"}


class OpenExternalLinkRequest(BaseModel):
    url: str


class DesktopDiagnosticRequest(BaseModel):
    source: str
    step: str
    url: str | None = None
    filename: str | None = None
    status: int | None = None
    bytes: int | None = None
    has_save_path: bool | None = None
    error: dict[str, str] | None = None


@router.post("/open-external-link", response_model=dict)
def open_external_link(payload: OpenExternalLinkRequest) -> dict:
    if os.environ.get(DESKTOP_APP_ENV) != "1":
        raise HTTPException(status_code=404, detail="Desktop API not available")

    url = payload.url
    _validate_external_url(url)
    logger.info("[desktop] opening external link: %s", _url_for_log(url))

    if not webbrowser.open(url):
        logger.warning(
            "[desktop] failed to open external link: %s",
            _url_for_log(url),
        )
        raise HTTPException(status_code=500, detail="Failed to open external link")

    return {"opened": True}


@router.post("/diagnostics", response_model=dict)
def record_desktop_diagnostic(payload: DesktopDiagnosticRequest) -> dict:
    if os.environ.get(DESKTOP_APP_ENV) != "1":
        raise HTTPException(status_code=404, detail="Desktop API not available")

    error = payload.error or {}
    logger.info(
        "[desktop-diagnostics] source=%s step=%s url=%s filename=%s "
        "status=%s bytes=%s has_save_path=%s error=%s:%s",
        _safe_log_text(payload.source),
        _safe_log_text(payload.step),
        _safe_log_text(payload.url),
        _safe_log_text(payload.filename),
        payload.status,
        payload.bytes,
        payload.has_save_path,
        _safe_log_text(error.get("name")),
        _safe_log_text(error.get("message")),
    )

    return {"logged": True}


def _validate_external_url(url: str) -> None:
    if not url or url.strip() != url:
        raise HTTPException(status_code=400, detail="Invalid external link")
    if any(char < " " for char in url):
        raise HTTPException(status_code=400, detail="Invalid external link")

    parsed = urlparse(url)
    if parsed.scheme.lower() not in SUPPORTED_EXTERNAL_SCHEMES:
        raise HTTPException(status_code=400, detail="Unsupported external link")
    if parsed.scheme.lower() in {"http", "https"} and not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid external link")


def _url_for_log(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme.lower() in {"http", "https"}:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"[:256]
    return f"{parsed.scheme}:"[:256]


def _safe_log_text(value: str | None, max_length: int = 256) -> str:
    if not value:
        return ""
    cleaned = "".join(char if char >= " " else " " for char in value)
    return cleaned[:max_length]
