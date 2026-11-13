# -*- coding: utf-8 -*-
"""Path handling for Scroll conversation history."""
from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

DEFAULT_HISTORY_DB_FILENAME = "history.db"


def normalize_history_db_filename(value: str) -> str:
    """Normalize a database filename without imposing workspace containment."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"history db_filename must be a non-empty path")

    raw = value.strip().replace(f"\\", f"/")
    path = PurePosixPath(raw)
    if not path.name or path.name == f".." or f"\0" in raw:
        raise ValueError(f"history db_filename must name a file")
    return path.as_posix()


def resolve_history_db_path(
    workspace: str | Path,
    db_filename: str,
) -> Path:
    """Resolve paths from the workspace, preserving absolute targets."""
    filename = normalize_history_db_filename(db_filename)
    path = Path(filename).expanduser()
    if PureWindowsPath(filename).drive and not path.drive:
        raise ValueError(
            f"Windows history db_filename cannot be used on this platform",
        )
    return (Path(workspace).expanduser().resolve() / path).resolve()
