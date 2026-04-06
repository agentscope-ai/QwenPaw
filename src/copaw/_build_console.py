# -*- coding: utf-8 -*-
"""Auto-build the console frontend when assets are missing or stale.

Used by:
  - ``setup.py`` — during ``pip install .`` (build_py) and legacy editable installs
  - ``_app.py``  — at application startup as a safety-net for PEP 660 editable installs
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("copaw.build_console")

# Resolve repo root: this file lives at src/copaw/_build_console.py
_THIS_DIR = Path(__file__).resolve().parent  # src/copaw/
_REPO_ROOT = _THIS_DIR.parent.parent  # repo root

_CONSOLE_DIR: Path | None = None
_CONSOLE_DIST: Path | None = None
_CONSOLE_DEST: Path | None = None
_CONSOLE_SRC: Path | None = None

# Detect console source directory — works both from source tree and editable install
_candidates = [
    _REPO_ROOT / "console",  # running from source tree
    _THIS_DIR.parent / "console",  # unlikely fallback
]
for _cand in _candidates:
    if (_cand / "package.json").exists():
        _CONSOLE_DIR = _cand
        _CONSOLE_DIST = _cand / "dist"
        _CONSOLE_SRC = _cand / "src"
        _CONSOLE_DEST = _THIS_DIR / "console"
        break


def _has_npm() -> bool:
    """Return True if npm is available on PATH."""
    try:
        subprocess.run(
            ["npm", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError, OSError):
        return False


def _needs_rebuild() -> bool:
    """Return True when console/dist is missing or source files are newer."""
    if _CONSOLE_DIST is None:
        return False

    if not _CONSOLE_DIST.exists() or not (_CONSOLE_DIST / "index.html").exists():
        return True

    try:
        dist_mtime = max(
            f.stat().st_mtime for f in _CONSOLE_DIST.rglob("*") if f.is_file()
        )
    except StopIteration:
        return True

    # Files/dirs whose modification should trigger a rebuild
    watch_dirs = [_CONSOLE_SRC] if _CONSOLE_SRC else []
    watch_files = [
        _CONSOLE_DIR / "package.json",
        _CONSOLE_DIR / "vite.config.ts",
        _CONSOLE_DIR / "tsconfig.json",
    ]
    for watch_dir in watch_dirs:
        if not watch_dir.exists():
            continue
        for f in watch_dir.rglob("*"):
            if f.is_file() and f.stat().st_mtime > dist_mtime:
                return True
    for f in watch_files:
        if f.exists() and f.stat().st_mtime > dist_mtime:
            return True

    return False


def build_console_frontend(*, quiet: bool = False) -> None:
    """Build the console frontend and copy to ``src/copaw/console/``.

    Parameters
    ----------
    quiet:
        When True, suppress stdout/stderr from npm.  Useful at app startup
        to avoid cluttering the log.
    """
    if _CONSOLE_DIR is None:
        return

    # Skip if no console source (e.g. installed from wheel without it)
    if not (_CONSOLE_DIR / "package.json").exists():
        return

    # Ensure dest is populated even when dist is already fresh
    if not _needs_rebuild():
        if _CONSOLE_DEST and not (_CONSOLE_DEST / "index.html").exists():
            _copy_dist()
        return

    if not _has_npm():
        logger.warning(
            "Console frontend is stale but npm not found — "
            "the web UI may be outdated.  "
            "Install Node.js and run: cd console && npm ci && npm run build",
        )
        return

    logger.info("Building console frontend …")
    try:
        out = subprocess.DEVNULL if quiet else sys.stdout
        err = subprocess.DEVNULL if quiet else sys.stderr
        subprocess.check_call(
            ["npm", "ci"],
            cwd=str(_CONSOLE_DIR),
            stdout=out,
            stderr=err,
        )
        subprocess.check_call(
            ["npm", "run", "build"],
            cwd=str(_CONSOLE_DIR),
            stdout=out,
            stderr=err,
        )
    except subprocess.CalledProcessError as exc:
        logger.warning("Console frontend build failed: %s", exc)
        return

    _copy_dist()
    logger.info("Console frontend built successfully.")


def _copy_dist() -> None:
    """Copy console/dist/* into src/copaw/console/."""
    if _CONSOLE_DEST is None or _CONSOLE_DIST is None:
        return
    if _CONSOLE_DEST.exists():
        shutil.rmtree(_CONSOLE_DEST)
    shutil.copytree(_CONSOLE_DIST, _CONSOLE_DEST)
