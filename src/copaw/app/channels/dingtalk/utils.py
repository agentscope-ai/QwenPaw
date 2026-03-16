# -*- coding: utf-8 -*-
"""DingTalk channel helpers (media suffix guess, filename cleanup, etc.)."""

import re
from pathlib import Path
from typing import Optional

# Magic bytes -> suffix for .file fallback (DingTalk URLs often return .file).
# AMR-NB voice: "#!AMR\n"
DINGTALK_MAGIC_SUFFIX: list[tuple[bytes, str]] = [
    (b"%PDF", ".pdf"),
    (b"PK\x03\x04", ".zip"),
    (b"PK\x05\x06", ".zip"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"\xd0\xcf\x11\xe0", ".doc"),
    (b"RIFF", ".webp"),
    (b"#!AMR\n", ".amr"),
]


def guess_suffix_from_bytes(data: bytes) -> Optional[str]:
    """Guess suffix from file magic bytes. Returns e.g. '.pdf' or None."""
    if not data:
        return None
    head = data[:32]
    for magic, suffix in DINGTALK_MAGIC_SUFFIX:
        if head.startswith(magic):
            return suffix
    return None


def guess_suffix_from_file_content(path: Path) -> Optional[str]:
    """Guess suffix from file magic bytes. Returns e.g. '.pdf' or None."""
    try:
        with open(path, "rb") as f:
            return guess_suffix_from_bytes(f.read(32))
    except Exception:
        return None


_INVALID_WINDOWS_FILENAME_RE = re.compile(r'[\x00-\x1f\\/:*?"<>|]+')
_WINDOWS_RESERVED_BASENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_download_filename(
    filename: str,
    fallback: str = "file",
) -> str:
    """Return a filesystem-safe basename while preserving Unicode."""
    fallback = (fallback or "file").strip() or "file"
    basename = (filename or "").strip().replace("\\", "/").split("/")[-1]
    basename = basename.strip()
    if not basename:
        basename = fallback
    sanitized = _INVALID_WINDOWS_FILENAME_RE.sub("_", basename)
    sanitized = sanitized.strip().strip(". ")
    sanitized = sanitized or fallback
    stem = Path(sanitized).stem or sanitized
    suffix = Path(sanitized).suffix
    normalized_stem = stem.rstrip(". ").upper()
    if normalized_stem in _WINDOWS_RESERVED_BASENAMES:
        sanitized = f"{stem}_{suffix}"
    return sanitized or fallback
