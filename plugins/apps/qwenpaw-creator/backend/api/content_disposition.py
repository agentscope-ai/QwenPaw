# -*- coding: utf-8 -*-
"""Shared response-header helpers for serving named Creator files."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import quote


def inline_content_disposition(name: str, media_type: str = "") -> str:
    """Build a Latin-1-safe inline filename with an RFC 5987 UTF-8 value.

    When *media_type* is provided and *name* has no suffix, a matching
    extension is appended so that downloaded files keep a usable extension.
    """

    original = Path(str(name or "media")).name or "media"
    if media_type and not Path(original).suffix:
        ext = mimetypes.guess_extension(media_type.split(";")[0].strip())
        if ext:
            original = f"{original}{ext}"
    fallback = "".join(
        character
        if 32 <= ord(character) < 127 and character not in {'"', "\\"}
        else "_"
        for character in original
    ).strip()
    suffix = Path(fallback).suffix
    stem = fallback[: -len(suffix)] if suffix else fallback
    if not stem.strip(" _.-"):
        suffix = suffix if suffix.strip("._") else ""
        fallback = f"media{suffix}"
    utf8_name = original.encode("utf-8", "replace").decode("utf-8", "replace")
    encoded_name = quote(utf8_name, safe="")
    return (
        f'inline; filename="{fallback}"; ' f"filename*=UTF-8''{encoded_name}"
    )


__all__ = ["inline_content_disposition"]
