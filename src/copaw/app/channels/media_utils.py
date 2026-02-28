# -*- coding: utf-8 -*-
"""Shared media classification helpers for channel adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

MediaKind = Literal["image", "video", "audio", "file"]

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"}
_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".amr"}


def classify_media_kind(*, mime_type: str = "", filename: str = "") -> MediaKind:
    """Classify media kind from mime type and filename suffix."""
    mt = (mime_type or "").strip().lower()
    suffix = Path((filename or "").strip().lower()).suffix
    if mt.startswith("image/") or suffix in _IMAGE_EXTS:
        return "image"
    if mt.startswith("video/") or suffix in _VIDEO_EXTS:
        return "video"
    if mt.startswith("audio/") or suffix in _AUDIO_EXTS:
        return "audio"
    return "file"


def pick_attachment_url(att: dict[str, Any]) -> str:
    """Pick best-effort URL field from heterogeneous attachment payloads."""
    for key in ("url", "file_url", "download_url", "content_url", "proxy_url"):
        value = att.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""

