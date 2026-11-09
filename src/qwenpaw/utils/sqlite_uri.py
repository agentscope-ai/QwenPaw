# -*- coding: utf-8 -*-
"""SQLite URI paths shared with the stdlib-only recall and backup workers."""

from pathlib import PurePath, PureWindowsPath
from typing import Literal
from urllib.parse import quote

_VERBATIM_PREFIX = "\\\\?\\"
_UNC_VERBATIM_PREFIX = "\\\\?\\UNC\\"


def _strip_windows_extended_prefix(value: str) -> str:
    """Remove the filesystem-only verbatim prefix before URI encoding."""
    if value[:8].casefold() == _UNC_VERBATIM_PREFIX.casefold():
        return "\\\\" + value[8:]
    if value.startswith(_VERBATIM_PREFIX):
        return value[4:]
    return value


def sqlite_uri(
    path: PurePath,
    mode: Literal["ro", "rw", "rwc"],
) -> str:
    """Encode an absolute POSIX, drive or UNC path with an empty authority."""
    text = str(path)
    if isinstance(path, PureWindowsPath):
        path = PureWindowsPath(_strip_windows_extended_prefix(text))
    # Unsupported verbatim volume roots become relative after stripping too.
    if not path.is_absolute():
        raise ValueError(
            f"sqlite_uri() needs an absolute path, got {text!r}.",
        )
    filename = path.as_posix()
    if isinstance(path, PureWindowsPath) and not filename.startswith("/"):
        filename = "/" + filename
    # Keep UNC hosts in the path; SQLite rejects non-local URI authorities.
    return f"file://{quote(filename, safe='/:')}?mode={mode}"
