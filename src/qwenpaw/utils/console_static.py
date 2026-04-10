# -*- coding: utf-8 -*-
"""Resolve the web console static assets directory (shared by app and CLI)."""
from __future__ import annotations

import os
from pathlib import Path

CONSOLE_STATIC_ENV = "COPAW_CONSOLE_STATIC_DIR"


def resolve_console_static_dir() -> str:
    """Return the directory expected to contain ``index.html`` for the console.

    Resolution order matches :mod:`copaw.app._app`: env override, package
    ``copaw/console``, repo ``console/dist``, then cwd fallbacks.
    """
    if os.environ.get(CONSOLE_STATIC_ENV):
        return os.environ[CONSOLE_STATIC_ENV]

    pkg_dir = Path(__file__).resolve().parent.parent
    candidate = pkg_dir / "console"
    if candidate.is_dir() and (candidate / "index.html").is_file():
        return str(candidate)

    repo_dir = pkg_dir.parent.parent
    candidate = repo_dir / "console" / "dist"
    if candidate.is_dir() and (candidate / "index.html").is_file():
        return str(candidate)

    cwd = Path(os.getcwd())
    for subdir in ("console/dist", "console_dist"):
        candidate = cwd / subdir
        if candidate.is_dir() and (candidate / "index.html").is_file():
            return str(candidate)

    return str(cwd / "console" / "dist")


def find_copaw_source_repo_root() -> Path | None:
    """Return the git checkout root if this Python is running from CoPaw source.

    Looks upward from :mod:`copaw` for ``console/package.json``,
    ``console/package-lock.json``, and ``src/copaw/`` (bundled static target).
    Returns ``None`` for a normal pip/wheel install.
    """
    try:
        import copaw  # noqa: PLC0415 — avoid import cycle at module load
    except Exception:  # pylint: disable=broad-exception-caught
        return None
    cur = Path(copaw.__file__).resolve().parent
    for _ in range(20):
        con = cur / "console"
        if (
            (con / "package.json").is_file()
            and (con / "package-lock.json").is_file()
            and (cur / "src" / "copaw").is_dir()
        ):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None
