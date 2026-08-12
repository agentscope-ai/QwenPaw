# -*- coding: utf-8 -*-
"""Bounded, cross-platform workspace snapshot and diff operations."""

import os
from dataclasses import dataclass
from pathlib import Path

from .exclusions import is_excluded_directory, is_excluded_file
from .models import (
    WorkspaceChange,
    WorkspaceFileState,
    WorkspaceSnapshot,
)


@dataclass(frozen=True, slots=True)
class SnapshotLimits:
    """Limits that keep workspace traversal predictable."""

    max_files: int = 10_000

    def __post_init__(self) -> None:
        if self.max_files < 1:
            raise ValueError(f"max_files must be positive: {self.max_files}")


def capture_workspace_snapshot(
    workspace_dir: Path,
    *,
    limits: SnapshotLimits | None = None,
) -> WorkspaceSnapshot:
    """Capture regular files without following directory or file links."""
    root = workspace_dir.resolve()
    active_limits = limits or SnapshotLimits()
    files: dict[str, WorkspaceFileState] = {}
    pending = [root]
    truncated = False

    while pending:
        directory = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError:
            continue

        child_directories: list[Path] = []
        for entry in entries:
            path = Path(entry.path)
            relative_path = path.relative_to(root)
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if not is_excluded_directory(relative_path):
                        child_directories.append(path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                if is_excluded_file(relative_path):
                    continue
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue

            normalized_path = relative_path.as_posix()
            files[normalized_path] = WorkspaceFileState(
                size=stat.st_size,
                modified_ns=stat.st_mtime_ns,
            )
            if len(files) >= active_limits.max_files:
                return WorkspaceSnapshot.create(files, truncated=True)

        pending.extend(reversed(child_directories))

    return WorkspaceSnapshot.create(files, truncated=truncated)


def diff_workspace_snapshots(
    before: WorkspaceSnapshot,
    after: WorkspaceSnapshot,
) -> tuple[WorkspaceChange, ...]:
    """Return deterministic created, modified, and deleted path changes."""
    changes: list[WorkspaceChange] = []
    all_paths = sorted(set(before.files) | set(after.files))
    for path in all_paths:
        old_state = before.files.get(path)
        new_state = after.files.get(path)
        if old_state is None:
            if not before.truncated:
                changes.append(WorkspaceChange(path, "created"))
        elif new_state is None:
            if not after.truncated:
                changes.append(WorkspaceChange(path, "deleted"))
        elif old_state != new_state:
            changes.append(WorkspaceChange(path, "modified"))
    return tuple(changes)
