# -*- coding: utf-8 -*-
"""SQLite URI paths shared with the stdlib-only recall and backup workers."""

from pathlib import PurePath, PureWindowsPath
from typing import Literal
from urllib.parse import quote


def _strip_windows_extended_prefix(value: str) -> str:
    """Remove the filesystem-only verbatim prefix before URI encoding."""
    if value[:8].casefold() == "\\\\?\\unc\\":
        return "\\\\" + value[8:]
    if value.startswith("\\\\?\\"):
        return value[4:]
    return value


def sqlite_uri(
    path: PurePath,
    mode: Literal["ro", "rw", "rwc"],
) -> str:
    """Encode an absolute database path with an empty URI authority."""
    if isinstance(path, PureWindowsPath):
        path = PureWindowsPath(_strip_windows_extended_prefix(str(path)))
    filename = path.as_posix()
    if isinstance(path, PureWindowsPath) and not filename.startswith("/"):
        filename = "/" + filename
    # Keep UNC hosts in the path; SQLite rejects non-local URI authorities.
    return f"file://{quote(filename, safe='/:')}?mode={mode}"
