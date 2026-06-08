# -*- coding: utf-8 -*-
"""File-access whitelist policy helpers."""

from __future__ import annotations

from dataclasses import dataclass
import ntpath
import os
import re
from pathlib import Path
from typing import Iterable, Literal

from ...config.context import get_current_workspace_dir
from ...constant import WORKING_DIR

FileAccessKind = Literal["read", "write"]

_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_WIN_UNC_RE = re.compile(r"^\\\\[^\\/?%*:|\"<>]+[\\/][^\\/?%*:|\"<>]+")


def _workspace_root() -> Path:
    return Path(get_current_workspace_dir() or WORKING_DIR)


def _is_windows_style_path(raw: str) -> bool:
    if not raw:
        return False
    if _WIN_DRIVE_RE.match(raw):
        return True
    if _WIN_UNC_RE.match(raw):
        return True
    if raw.startswith((".\\", "..\\", "\\")):
        return True
    if "\\" in raw:
        return True
    return False


def normalize_access_path(raw_path: str) -> str:
    """Normalize a path string to canonical absolute form."""
    if not isinstance(raw_path, str):
        return ""
    raw = raw_path.strip()
    if not raw:
        return ""

    if os.name == "nt" or _is_windows_style_path(raw):
        expanded = os.path.expanduser(raw) if raw.startswith("~") else raw
        if not ntpath.isabs(expanded):
            expanded = ntpath.join(str(_workspace_root()), expanded)
        normalized = ntpath.normpath(expanded)
        return normalized.replace("\\", "/").lower()

    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = _workspace_root() / p
    return str(p.resolve(strict=False))


def _classify_roots(paths: Iterable[str]) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    dirs: set[str] = set()
    for path in paths:
        if not path:
            continue
        normalized = normalize_access_path(path)
        if not normalized:
            continue
        p = Path(normalized)
        if p.is_dir() or path.endswith(("/", "\\")):
            dirs.add(normalized.rstrip("/\\"))
        else:
            files.add(normalized)
    return files, dirs


def _path_in_roots(
    normalized_path: str,
    root_files: set[str],
    root_dirs: set[str],
) -> bool:
    if not normalized_path:
        return False
    if normalized_path in root_files:
        return True
    for dir_path in root_dirs:
        if not dir_path:
            continue
        if normalized_path == dir_path:
            return True
        if normalized_path.startswith(dir_path + "/"):
            return True
        if normalized_path.startswith(dir_path + "\\"):
            return True
    return False


@dataclass(frozen=True)
class FileWhitelistPolicy:
    """In-memory whitelist policy resolved from config."""

    enabled: bool
    read_files: set[str]
    read_dirs: set[str]
    write_files: set[str]
    write_dirs: set[str]

    @classmethod
    def from_config(cls) -> "FileWhitelistPolicy":
        try:
            from qwenpaw.config import load_config

            fg = load_config().security.file_guard
            enabled = bool(getattr(fg, "whitelist_enabled", False))
            read_paths = list(getattr(fg, "whitelist_read_paths", []) or [])
            write_paths = list(
                getattr(fg, "whitelist_write_paths", []) or [],
            )
            read_files, read_dirs = _classify_roots(read_paths)
            write_files, write_dirs = _classify_roots(write_paths)
            return cls(
                enabled=enabled,
                read_files=read_files,
                read_dirs=read_dirs,
                write_files=write_files,
                write_dirs=write_dirs,
            )
        except Exception:
            return cls(
                enabled=False,
                read_files=set(),
                read_dirs=set(),
                write_files=set(),
                write_dirs=set(),
            )

    def allows(self, path: str, access: FileAccessKind) -> bool:
        """Return whether *path* is allowed for the given access kind."""
        if not self.enabled:
            return True
        normalized = normalize_access_path(path)
        if not normalized:
            return False
        if access == "read":
            # Write roots also imply readable roots.
            return _path_in_roots(
                normalized,
                root_files=(self.read_files | self.write_files),
                root_dirs=(self.read_dirs | self.write_dirs),
            )
        return _path_in_roots(
            normalized,
            root_files=self.write_files,
            root_dirs=self.write_dirs,
        )

    def allowed_roots_for_shell(self) -> tuple[list[str], list[str]]:
        read_roots = sorted(self.read_files | self.read_dirs)
        write_roots = sorted(self.write_files | self.write_dirs)
        return read_roots, write_roots
