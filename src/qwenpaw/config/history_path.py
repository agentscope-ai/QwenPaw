# -*- coding: utf-8 -*-
"""Canonical, workspace-bounded paths for Scroll conversation history."""
from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

DEFAULT_HISTORY_DB_FILENAME = "history.db"


def normalize_history_db_filename(value: str) -> str:
    """Validate and normalize a workspace-relative history DB filename."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("history db_filename must be a non-empty path")

    raw = value.strip()
    windows_path = PureWindowsPath(raw)
    posix_path = PurePosixPath(raw.replace("\\", "/"))
    if (
        raw.startswith("~")
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
    ):
        raise ValueError(
            "history db_filename must be relative to the agent workspace",
        )

    parts = posix_path.parts
    if not parts or any(part == ".." for part in parts):
        raise ValueError(
            "history db_filename must not escape the agent workspace",
        )
    return PurePosixPath(*parts).as_posix()


def resolve_history_db_path(
    workspace: str | Path,
    db_filename: str,
) -> Path:
    """Resolve a validated history path and reject symlink escapes."""
    root = Path(workspace).expanduser().resolve()
    filename = normalize_history_db_filename(db_filename)
    candidate = (root / filename).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(
            "history db_filename resolves outside the agent workspace",
        )
    return candidate
