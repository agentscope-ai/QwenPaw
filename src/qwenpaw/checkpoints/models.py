# -*- coding: utf-8 -*-
"""Data models and the shared error type for the checkpoints subsystem."""

from __future__ import annotations

from dataclasses import dataclass


class CheckpointError(RuntimeError):
    """Raised when a checkpoint operation cannot complete."""


@dataclass(frozen=True)
class CheckpointEntry:
    """One checkpoint in a session timeline / graph."""

    ref: str
    kind: str  # "auto" | "snap" | "pre-restore" | "sha"
    session_key: str
    name: str
    commit: str
    timestamp_ms: int
    subject: str
    query: str | None
    channel: str = "unknown"
    restore_index: int | None = None
    parent_commit: str | None = None
    is_head: bool = False
    user_id: str = ""
    session_id: str = ""


@dataclass(frozen=True)
class SnapshotResult:
    """Internal result of creating one checkpoint snapshot."""

    ref: str
    commit: str
    tree: str
    parent_commit: str | None
    timestamp_ms: int


@dataclass(frozen=True)
class RestorePlan:
    """Immutable description of a restore before workspace mutation."""

    target: str
    commit: str
    conversation_path: str
    restore_paths: tuple[str, ...] = ()
    delete_paths: tuple[str, ...] = ()
    file_paths: tuple[str, ...] = ()
    include_memory: bool = False
    include_files: bool = False


@dataclass(frozen=True)
class RestoreResult:
    """Result of a conversation / memory / files restore."""

    target: str
    commit: str
    restored_paths: tuple[str, ...]
    pre_restore_ref: str | None
    dry_run: bool
    include_memory: bool = False
    include_files: bool = False
    deleted_paths: tuple[str, ...] = ()
    file_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class GcResult:
    """Result of a checkpoint GC pass."""

    deleted_refs: tuple[str, ...]
    kept_refs: tuple[str, ...]
    dry_run: bool
