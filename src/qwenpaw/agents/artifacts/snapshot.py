# -*- coding: utf-8 -*-
"""Bounded, cross-platform workspace snapshot and diff operations."""

import hashlib
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
    max_fingerprint_bytes: int = 32 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.max_files < 1:
            raise ValueError(f"max_files must be positive: {self.max_files}")
        if self.max_fingerprint_bytes < 0:
            raise ValueError(
                f"max_fingerprint_bytes must not be negative: "
                f"{self.max_fingerprint_bytes}",
            )


def _fingerprint_file(path: Path) -> str:
    """Hash one regular file after its metadata has been accepted."""
    digest = hashlib.blake2b(digest_size=16)
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _capture_fingerprint(
    path: Path,
    size: int,
    consumed_bytes: int,
    max_bytes: int,
) -> tuple[str | None, int, bool]:
    """Capture a fingerprint while respecting the total byte budget."""
    if consumed_bytes + size > max_bytes:
        return None, consumed_bytes, True
    try:
        fingerprint = _fingerprint_file(path)
    except OSError:
        return None, consumed_bytes, True
    return fingerprint, consumed_bytes + size, False


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
    fingerprint_bytes = 0
    fingerprints_truncated = False

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
            (
                fingerprint,
                fingerprint_bytes,
                fingerprint_missing,
            ) = _capture_fingerprint(
                path,
                stat.st_size,
                fingerprint_bytes,
                active_limits.max_fingerprint_bytes,
            )
            fingerprints_truncated |= fingerprint_missing
            files[normalized_path] = WorkspaceFileState(
                size=stat.st_size,
                modified_ns=stat.st_mtime_ns,
                fingerprint=fingerprint,
            )
            if len(files) >= active_limits.max_files:
                return WorkspaceSnapshot.create(
                    files,
                    truncated=True,
                    fingerprints_truncated=fingerprints_truncated,
                )

        pending.extend(reversed(child_directories))

    return WorkspaceSnapshot.create(
        files,
        truncated=truncated,
        fingerprints_truncated=fingerprints_truncated,
    )


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
        elif (
            old_state.size != new_state.size
            or old_state.modified_ns != new_state.modified_ns
            or (
                old_state.fingerprint is not None
                and new_state.fingerprint is not None
                and old_state.fingerprint != new_state.fingerprint
            )
        ):
            changes.append(WorkspaceChange(path, "modified"))
    return tuple(changes)
