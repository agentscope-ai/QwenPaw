# -*- coding: utf-8 -*-
"""Pure path parsing helpers for media URL sources."""

from __future__ import annotations

from urllib.parse import unquote, urlparse

_REMOTE_MEDIA_SCHEMES = frozenset(
    {"data", "ftp", "gs", "http", "https", "oss", "s3"},
)


def file_url_to_path(url: str) -> str:
    """Convert a file URI to a cross-platform local path string."""
    if not url.startswith("file://"):
        return unquote(url)
    value = url[7:]
    if value.startswith("localhost/"):
        value = value[9:]
    if (
        len(value) >= 3
        and value.startswith("/")
        and value[1].isalpha()
        and value[2] == ":"
    ):
        value = value[1:]
    elif len(value) >= 2 and value[0].isalpha() and value[1] == ":":
        pass
    elif not value.startswith("/"):
        value = f"//{value}"
    return unquote(value)


def local_media_path(url: str) -> str | None:
    """Return a local media path, or ``None`` for a remote URL."""
    path = file_url_to_path(url)
    scheme = urlparse(path).scheme
    if scheme in _REMOTE_MEDIA_SCHEMES:
        return None
    is_windows_drive = len(path) >= 2 and path[0].isalpha() and path[1] == ":"
    if scheme and not is_windows_drive:
        return None
    return path or None
