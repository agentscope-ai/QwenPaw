# -*- coding: utf-8 -*-
"""SQLite URI paths shared with the stdlib-only recall and backup workers."""

from pathlib import PurePath, PureWindowsPath
from typing import Literal
from urllib.parse import quote

_VERBATIM_PREFIX = "\\\\?\\"
_UNC_VERBATIM_PREFIX = "\\\\?\\UNC\\"
# Verbatim roots with no plain drive-letter or UNC spelling. Dropping the
# ``\\?\`` prefix turns them into ordinary relative names, so the URI would
# silently point at a same-named directory instead of the volume.
_UNSUPPORTED_VERBATIM_ROOTS = ("volume{", "globalroot")


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
    r"""Encode an absolute database path with an empty URI authority.

    Args:
        path: Absolute filesystem path (POSIX, drive letter, or UNC).
        mode: SQLite connection mode appended to the URI.

    Raises:
        ValueError: The path is relative — it would land in the URI
            authority slot — or it is a verbatim ``Volume{GUID}`` /
            ``GLOBALROOT`` path, which only names a file while the
            ``\\?\`` prefix is intact.
    """
    if isinstance(path, PureWindowsPath):
        text = str(path)
        is_unc = text[:8].casefold() == _UNC_VERBATIM_PREFIX.casefold()
        if text.startswith(_VERBATIM_PREFIX) and not is_unc:
            root = text[4:].split("\\", 1)[0].casefold()
            if root.startswith(_UNSUPPORTED_VERBATIM_ROOTS):
                raise ValueError(
                    "sqlite_uri() cannot encode the verbatim path "
                    f"{text!r}: it has no drive-letter or UNC equivalent, "
                    "so pass the resolved drive path instead.",
                )
        path = PureWindowsPath(_strip_windows_extended_prefix(text))
    if not path.is_absolute():
        raise ValueError(
            f"sqlite_uri() needs an absolute path, got {str(path)!r}.",
        )
    filename = path.as_posix()
    if isinstance(path, PureWindowsPath) and not filename.startswith("/"):
        filename = "/" + filename
    # Keep UNC hosts in the path; SQLite rejects non-local URI authorities.
    return f"file://{quote(filename, safe='/:')}?mode={mode}"
