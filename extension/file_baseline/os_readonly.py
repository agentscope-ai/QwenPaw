# -*- coding: utf-8
"""OS-level read-only flag for file-baseline protected workspace files."""
from __future__ import annotations

import logging
import os
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


def is_os_readonly(path: Path) -> bool:
    """Return True when the file appears read-only at the OS level."""
    if not path.is_file():
        return False
    if os.name == "nt":
        proc = subprocess.run(
            ["attrib", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0 and " R " in f" {proc.stdout.upper()} ":
            return True
    mode = path.stat().st_mode
    return not (mode & stat.S_IWUSR)


def set_os_readonly(path: Path) -> bool:
    """Mark an existing file read-only. Returns True when applied."""
    if not path.is_file():
        return False
    try:
        if os.name == "nt":
            proc = subprocess.run(
                ["attrib", "+R", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                logger.warning(
                    "file_baseline_os_readonly set_failed path=%s stderr=%s",
                    path,
                    (proc.stderr or proc.stdout or "").strip(),
                )
                return False
        else:
            mode = path.stat().st_mode
            path.chmod(mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
        logger.info("file_baseline_os_readonly set path=%s", path)
        return True
    except OSError as exc:
        logger.warning("file_baseline_os_readonly set_error path=%s err=%s", path, exc)
        return False


def clear_os_readonly(path: Path) -> bool:
    """Clear OS read-only on an existing file. Returns True when cleared."""
    if not path.is_file():
        return False
    try:
        if os.name == "nt":
            proc = subprocess.run(
                ["attrib", "-R", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                logger.warning(
                    "file_baseline_os_readonly clear_failed path=%s stderr=%s",
                    path,
                    (proc.stderr or proc.stdout or "").strip(),
                )
                return False
        else:
            mode = path.stat().st_mode
            path.chmod(mode | stat.S_IWUSR)
        logger.info("file_baseline_os_readonly clear path=%s", path)
        return True
    except OSError as exc:
        logger.warning("file_baseline_os_readonly clear_error path=%s err=%s", path, exc)
        return False


def absolute_paths_for_relative_paths(
    workspace: Path,
    relative_paths: list[str],
) -> list[Path]:
    resolved: list[Path] = []
    seen: set[str] = set()
    for rel in relative_paths:
        candidate = (workspace / rel).resolve(strict=False)
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            resolved.append(candidate)
    return resolved


def apply_os_readonly_for_paths(workspace: Path, relative_paths: list[str]) -> None:
    for absolute in absolute_paths_for_relative_paths(workspace, relative_paths):
        set_os_readonly(absolute)


def clear_os_readonly_for_paths(workspace: Path, relative_paths: list[str]) -> None:
    for absolute in absolute_paths_for_relative_paths(workspace, relative_paths):
        clear_os_readonly(absolute)


def append_external_edit(path: Path, suffix: str, *, encoding: str = "utf-8") -> None:
    """Simulate an external editor append (clears OS read-only briefly if needed)."""
    existing = path.read_text(encoding=encoding) if path.is_file() else ""
    write_external_content(path, existing + suffix, encoding=encoding)


def write_external_content(
    path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Write as an external process would (briefly clears OS read-only if set)."""
    was_readonly = is_os_readonly(path) if path.is_file() else False
    if was_readonly:
        clear_os_readonly(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)
    finally:
        if was_readonly:
            set_os_readonly(path)


@contextmanager
def temporary_os_writable(paths: list[Path]) -> Iterator[None]:
    """Temporarily clear OS read-only for approved writes; restore in ``finally``."""
    touched: list[Path] = []
    for path in paths:
        if path.is_file() and is_os_readonly(path) and clear_os_readonly(path):
            touched.append(path)
    try:
        yield
    finally:
        for path in touched:
            set_os_readonly(path)
