# -*- coding: utf-8 -*-
"""Find the Antigravity CLI executable."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

_BINARY_NAMES = ("agy", "agy.exe")


@dataclass(frozen=True)
class AgyBinaryResolution:
    """Resolved Antigravity CLI path and where it was found."""

    path: Path
    source: str


def default_install_candidates(
    user_home: Path | None = None,
) -> list[tuple[Path, str]]:
    """Return the places the Antigravity CLI installer puts the binary."""
    home = user_home or Path.home()
    return [
        (home / ".local" / "bin" / name, "local-bin") for name in _BINARY_NAMES
    ]


def resolve_agy_binary_info(
    explicit: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    user_home: Path | None = None,
) -> AgyBinaryResolution | None:
    """Resolve the CLI: configured path, then PATH, then installer default.

    A configured path that is not an executable file resolves to nothing:
    falling back to another install would run a binary the user did not
    choose.
    """
    configured = (explicit or "").strip()
    if configured:
        path = Path(configured).expanduser()
        if _is_executable(path):
            return AgyBinaryResolution(path.resolve(), "configured")
        return None
    environment = environ if environ is not None else os.environ
    for name in _BINARY_NAMES:
        found = shutil.which(name, path=environment.get("PATH"))
        if found:
            return AgyBinaryResolution(Path(found).resolve(), "path")
    for candidate, source in default_install_candidates(user_home):
        if _is_executable(candidate):
            return AgyBinaryResolution(candidate.resolve(), source)
    return None


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


__all__ = [
    "AgyBinaryResolution",
    "default_install_candidates",
    "resolve_agy_binary_info",
]
