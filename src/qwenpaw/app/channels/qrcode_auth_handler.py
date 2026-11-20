# -*- coding: utf-8 -*-
"""SDK-free QR session results and local QR image generation.

Platform authorization runs through descriptor-selected management workers.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import Any, Dict

import segno
from fastapi import HTTPException


@dataclass
class QRCodeResult:
    """Value object returned by ``fetch_qrcode``."""

    scan_url: str
    poll_token: str


@dataclass
class PollResult:
    """Value object returned by ``poll_status``."""

    status: str
    credentials: Dict[str, Any]


def generate_qrcode_image(scan_url: str) -> str:
    """Generate a base64-encoded PNG QR code image from *scan_url*."""
    try:
        qr_code = segno.make(scan_url, error="M")
        buf = io.BytesIO()
        qr_code.save(buf, kind="png", scale=6, border=2)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"QR code image generation failed: {exc}",
        ) from exc
