# -*- coding: utf-8 -*-
"""Default exclusions for bounded workspace artifact scans."""

import re
from pathlib import Path

from ...workspace_state import is_qwenpaw_state_path

_ROOT_SESSION_JSONL_PATTERN = re.compile(r"^[0-9a-fA-F]{32}\.jsonl$")

EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".qwenpaw",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
    },
)

EXCLUDED_FILE_NAMES = frozenset(
    {
        "history.db",
        "history.db-shm",
        "history.db-wal",
    },
)

EXCLUDED_FILE_SUFFIXES = (
    ".lock",
    ".part",
    ".swp",
    ".swo",
    ".tmp",
    "~",
)


def is_excluded_directory(relative_path: Path) -> bool:
    """Return whether a relative directory contains internal runtime data."""
    normalized = relative_path.as_posix().rstrip("/")
    return (
        relative_path.name in EXCLUDED_DIRECTORY_NAMES
        or is_qwenpaw_state_path(f"{normalized}/")
    )


def is_excluded_file(relative_path: Path) -> bool:
    """Return whether a relative file is internal or temporary state."""
    name = relative_path.name
    has_excluded_parent = any(
        part in EXCLUDED_DIRECTORY_NAMES for part in relative_path.parts[:-1]
    )
    is_root_session = (
        len(relative_path.parts) == 1
        and _ROOT_SESSION_JSONL_PATTERN.fullmatch(name) is not None
    )
    return (
        name in EXCLUDED_FILE_NAMES
        or name.endswith(EXCLUDED_FILE_SUFFIXES)
        or has_excluded_parent
        or is_qwenpaw_state_path(relative_path.as_posix())
        or is_root_session
    )
