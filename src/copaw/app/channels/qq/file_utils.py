# -*- coding: utf-8 -*-
"""File utility helpers for QQ media sending."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

is_windows: bool = sys.platform.startswith("win")

_REMOTE_URL_SCHEMES = {
    "http",
    "https",
    "ftp",
    "ftps",
    "ws",
    "wss",
    "s3",
    "oss",
    "data",
    "file",
}

_AUDIO_EXTENSIONS = {
    "aac",
    "amr",
    "flac",
    "m4a",
    "mp3",
    "ogg",
    "opus",
    "silk",
    "wav",
    "wma",
}

_FILE_TYPE_NAMES = {
    "image": "Image",
    "video": "Video",
    "audio": "Voice",
    "application/pdf": "PDF",
    "text/plain": "Text",
}

_MAX_UPLOAD_SIZES = {
    "image": 30 * 1024 * 1024,
    "video": 100 * 1024 * 1024,
    "voice": 10 * 1024 * 1024,
    "file": 100 * 1024 * 1024,
}


def is_local_path(path: str) -> bool:  # pylint: disable=too-many-return-statements
    """Return ``True`` when *path* looks like a local filesystem path."""

    if not path or not path.strip():
        return False

    candidate = path.strip()

    if candidate.startswith(("\\\\", "//")):
        return True

    if len(candidate) >= 3 and candidate[1] == ":" and candidate[2] in "\\/":
        return True

    if candidate.startswith(("~", ".", os.sep, "/", "\\")):
        return True

    parsed = urlparse(candidate)
    if parsed.scheme.lower() in _REMOTE_URL_SCHEMES:
        return False
    if parsed.netloc:
        return False

    return True


def normalize_path(path: str) -> str:
    """Normalize separators for local file paths."""

    if not path:
        return path

    normalized = path.strip()
    if not is_local_path(normalized):
        return normalized

    if is_windows:
        normalized = normalized.replace("/", "\\")
    else:
        normalized = normalized.replace("\\", "/")

    return os.path.normpath(normalized)


def get_file_hash(file_path: str, algorithm: str = "sha256") -> str:
    """Compute the hash for *file_path* using *algorithm*."""

    hasher = hashlib.new(algorithm)
    with open(file_path, "rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_file_size(file_path: str) -> int:
    """Return the file size in bytes."""

    return os.path.getsize(file_path)


def file_exists(file_path: str) -> bool:
    """Return ``True`` when *file_path* exists and is a file."""

    return Path(file_path).is_file()


def format_file_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable string."""

    if size_bytes < 1024:
        return f"{size_bytes} B"

    size = float(size_bytes)
    for unit in ("KB", "MB", "GB", "TB"):
        size /= 1024.0
        if size < 1024.0 or unit == "TB":
            if size.is_integer():
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"

    return f"{size_bytes} B"


def get_file_type_name(mime_type: str) -> str:
    """Return a readable file type name for *mime_type*."""

    normalized = (mime_type or "").split(";", 1)[0].strip().lower()
    if not normalized:
        return "File"
    if normalized in _FILE_TYPE_NAMES:
        return _FILE_TYPE_NAMES[normalized]
    if normalized.startswith("image/"):
        return "Image"
    if normalized.startswith("video/"):
        return "Video"
    if normalized.startswith("audio/"):
        return "Voice"
    return "File"


def get_max_upload_size(mime_type: str) -> int:
    """Return the QQ upload size limit in bytes for *mime_type*."""

    normalized = (mime_type or "").split(";", 1)[0].strip().lower()
    if normalized.startswith("image/"):
        return _MAX_UPLOAD_SIZES["image"]
    if normalized.startswith("video/"):
        return _MAX_UPLOAD_SIZES["video"]
    if normalized.startswith("audio/"):
        return _MAX_UPLOAD_SIZES["voice"]
    return _MAX_UPLOAD_SIZES["file"]


def is_audio_file(file_path: str) -> bool:
    """Return ``True`` when *file_path* has a known audio extension."""

    return get_extension(file_path) in _AUDIO_EXTENSIONS


def get_extension(file_path: str) -> str:
    """Return the lowercase file extension without the leading dot."""

    return Path(file_path).suffix.lower().lstrip(".")


__all__ = [
    "file_exists",
    "format_file_size",
    "get_extension",
    "get_file_hash",
    "get_file_size",
    "get_file_type_name",
    "get_max_upload_size",
    "is_audio_file",
    "is_local_path",
    "is_windows",
    "normalize_path",
]
