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
