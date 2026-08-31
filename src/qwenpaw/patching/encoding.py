# -*- coding: utf-8 -*-
"""Decode and re-encode patch targets without changing text conventions."""

from __future__ import annotations

import stat
from pathlib import Path

from .errors import PatchError
from .models import TextSnapshot

_BOM = b"\xef\xbb\xbf"


def decode_snapshot(path: Path, raw: bytes) -> TextSnapshot:
    bom = raw.startswith(_BOM)
    payload = raw[len(_BOM) :] if bom else raw
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PatchError(
            "unsupported_encoding",
            f"{path} is not valid UTF-8 text",
        ) from exc
    crlf = decoded.count("\r\n")
    without_crlf = decoded.replace("\r\n", "")
    cr = without_crlf.count("\r")
    lf = without_crlf.count("\n")
    newline = (
        "\r\n" if crlf >= max(cr, lf) and crlf else ("\r" if cr > lf else "\n")
    )
    normalized = decoded.replace("\r\n", "\n").replace("\r", "\n")
    trailing = normalized.endswith("\n")
    if trailing:
        normalized = normalized[:-1]
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    return TextSnapshot(path, raw, normalized, newline, trailing, bom, mode)


def encode_text(
    text: str,
    *,
    newline: str,
    trailing_newline: bool,
    bom: bool,
) -> bytes:
    rendered = text.replace("\n", newline)
    if trailing_newline:
        rendered += newline
    payload = rendered.encode("utf-8")
    return (_BOM + payload) if bom else payload
