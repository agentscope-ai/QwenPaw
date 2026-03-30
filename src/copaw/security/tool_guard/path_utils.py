# -*- coding: utf-8 -*-
"""Shared path helpers for tool-guard style checks."""
from __future__ import annotations

import ntpath
import re
from pathlib import Path, PureWindowsPath
from typing import Iterable

GuardPath = Path | PureWindowsPath

_WINDOWS_ABS_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


def _is_windows_path(raw: str) -> bool:
    return bool(_WINDOWS_ABS_RE.match(raw.strip()))


def _uses_windows_flavor(*values: str) -> bool:
    return any(_is_windows_path(value) for value in values if value)


def _expand_user(raw: str) -> str:
    if not raw.startswith("~"):
        return raw

    home = str(Path.home())
    if raw == "~":
        return home
    if raw.startswith("~/") or raw.startswith("~\\"):
        suffix = raw[2:]
        if _uses_windows_flavor(raw, home):
            return str(PureWindowsPath(home, suffix))
        return str(Path(home) / suffix)
    return raw


def resolve_path(
    raw_path: str | Path | GuardPath,
    base_dir: str | Path | GuardPath,
) -> GuardPath:
    """Resolve *raw_path* against *base_dir* using a stable path flavor."""
    raw = _expand_user(str(raw_path).strip() or ".")
    base = _expand_user(str(base_dir).strip() or ".")

    if _uses_windows_flavor(raw, base):
        base_path = PureWindowsPath(ntpath.normpath(base))
        path_obj = PureWindowsPath(raw)
        if not path_obj.is_absolute():
            path_obj = PureWindowsPath(base_path, path_obj)
        return PureWindowsPath(ntpath.normpath(str(path_obj)))

    base_path = Path(base).expanduser().resolve(strict=False)
    path_obj = Path(raw).expanduser()
    if not path_obj.is_absolute():
        path_obj = base_path / path_obj
    return path_obj.resolve(strict=False)


def is_within_root(
    path: str | Path | GuardPath,
    root: str | Path | GuardPath,
) -> bool:
    """Return True when *path* resolves within *root*."""
    resolved_root = resolve_path(root, root)
    resolved_path = resolve_path(path, resolved_root)

    if isinstance(resolved_root, PureWindowsPath) != isinstance(
        resolved_path,
        PureWindowsPath,
    ):
        return False

    try:
        return resolved_path.is_relative_to(resolved_root)
    except AttributeError:  # pragma: no cover
        try:
            resolved_path.relative_to(resolved_root)
        except ValueError:
            return False
        return True


def normalize_guard_path(
    raw_path: str | Path | GuardPath,
    base_dir: str | Path | GuardPath,
) -> str:
    """Normalize *raw_path* into a canonical absolute path string."""
    return str(resolve_path(raw_path, base_dir))


def _is_directory_guard(raw_path: str, normalized_path: GuardPath) -> bool:
    if raw_path.endswith(("/", "\\")):
        return True
    return isinstance(normalized_path, Path) and normalized_path.is_dir()


def matches_sensitive_path(
    path: str | Path | GuardPath,
    sensitive_files: Iterable[str],
    *,
    base_dir: str | Path | GuardPath,
) -> bool:
    """Return True when *path* matches sensitive file or directory guards."""
    resolved_path = resolve_path(path, base_dir)
    for raw_sensitive in sensitive_files:
        if not raw_sensitive:
            continue
        normalized_sensitive = resolve_path(raw_sensitive, base_dir)
        if _is_directory_guard(raw_sensitive, normalized_sensitive):
            if is_within_root(resolved_path, normalized_sensitive):
                return True
            continue
        if str(resolved_path) == str(normalized_sensitive):
            return True
    return False


__all__ = [
    "GuardPath",
    "is_within_root",
    "matches_sensitive_path",
    "normalize_guard_path",
    "resolve_path",
]
