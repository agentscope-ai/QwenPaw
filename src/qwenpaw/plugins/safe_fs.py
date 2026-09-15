# -*- coding: utf-8 -*-
"""Guarded deletes and filesystem identity for plugin transactions.

Empty or relative paths are a no-op / refusal, never the process cwd.
``Path("")`` and ``Path(".")`` are the current working directory; callers
must not treat a missing JSON field as a deletable path.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_REPO_MARKERS = (".git", "pyproject.toml", "setup.py")


def _repo_root() -> Path | None:
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if any((parent / marker).exists() for marker in _REPO_MARKERS):
            return parent
    return None


def _forbidden_roots() -> set[Path]:
    roots = {Path.cwd().resolve(), Path("/").resolve()}
    try:
        roots.add(Path.home().resolve())
    except OSError:
        pass
    repo = _repo_root()
    if repo is not None:
        roots.add(repo)
    return roots


def parse_optional_absolute(raw: object) -> Path | None:
    """Return an absolute path, or ``None`` when the field is missing."""
    text = str(raw or "").strip()
    if not text:
        return None
    path = Path(text)
    if not path.is_absolute():
        return None
    return path


def ensure_deletable(path: Path, *, purpose: str = "delete") -> Path:
    """Refuse cwd, repo root, home, ``/``, relatives, and empty paths."""
    raw = str(path).strip() if path is not None else ""
    if not raw:
        raise ValueError(f"refusing to {purpose} an empty path")
    if not path.is_absolute():
        raise ValueError(f"refusing to {purpose} relative path {path}")
    resolved = path.resolve()
    if resolved in _forbidden_roots():
        raise ValueError(f"refusing to {purpose} {path}")
    cwd = Path.cwd().resolve()
    if resolved == cwd or resolved in cwd.parents:
        raise ValueError(f"refusing to {purpose} ancestor {path}")
    return resolved


def safe_remove(path: Path | None, *, purpose: str = "delete") -> None:
    """Remove a file or directory after :func:`ensure_deletable`.

    Missing paths and ``None`` are no-ops. Empty / relative values raise
    rather than falling through to cwd.
    """
    if path is None:
        return
    raw = str(path).strip()
    if not raw:
        raise ValueError(f"refusing to {purpose} an empty path")
    if not path.exists():
        return
    resolved = ensure_deletable(path, purpose=purpose)
    if resolved.is_dir():
        shutil.rmtree(resolved)
        return
    resolved.unlink()


def same_location(left: Path, right: Path) -> bool:
    """True when both paths name the same filesystem object.

    Use identity (``samefile``) when both exist. Only fall back to
    resolved-string comparison when a target does not exist yet.
    """
    left = Path(left)
    right = Path(right)
    if left.exists() and right.exists():
        try:
            return os.path.samestat(left.stat(), right.stat())
        except OSError:
            try:
                return left.samefile(right)
            except OSError:
                pass
    return left.resolve() == right.resolve()
