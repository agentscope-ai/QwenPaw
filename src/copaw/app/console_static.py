# -*- coding: utf-8 -*-
"""Helpers for resolving the built console's static directory."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

CONSOLE_STATIC_ENV = "COPAW_CONSOLE_STATIC_DIR"


def _absolute_path(
    path: str | os.PathLike[str],
    *,
    base_dir: Path | None = None,
) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = (base_dir or Path.cwd()) / candidate
    return candidate.resolve()


def is_console_static_dir(path: Path) -> bool:
    """Return whether the directory contains a built console entrypoint."""
    return path.is_dir() and (path / "index.html").is_file()


def iter_console_static_candidates(
    *,
    module_file: str | os.PathLike[str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> tuple[Path, ...]:
    """Yield candidate console directories in priority order."""
    base_cwd = _absolute_path(cwd or Path.cwd())
    module_path = _absolute_path(module_file or __file__)

    # console_static.py lives in src/copaw/app/, so parent.parent is src/copaw.
    pkg_dir = module_path.parent.parent
    repo_root = pkg_dir.parent.parent

    candidates = (
        pkg_dir / "console",
        repo_root / "console" / "dist",
        repo_root / "console_dist",
        base_cwd / "console" / "dist",
        base_cwd / "console_dist",
    )

    unique_candidates: list[Path] = []
    for candidate in candidates:
        normalized = _absolute_path(candidate, base_dir=base_cwd)
        if normalized not in unique_candidates:
            unique_candidates.append(normalized)

    return tuple(unique_candidates)


def resolve_console_static_dir(
    *,
    env: Mapping[str, str] | None = None,
    module_file: str | os.PathLike[str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> str:
    """Resolve the static console directory to an absolute path."""
    base_cwd = _absolute_path(cwd or Path.cwd())
    env_map = os.environ if env is None else env
    override = env_map.get(CONSOLE_STATIC_ENV)
    if override:
        return str(_absolute_path(override, base_dir=base_cwd))

    for candidate in iter_console_static_candidates(
        module_file=module_file,
        cwd=base_cwd,
    ):
        if is_console_static_dir(candidate):
            return str(candidate)

    return str((base_cwd / "console" / "dist").resolve())
