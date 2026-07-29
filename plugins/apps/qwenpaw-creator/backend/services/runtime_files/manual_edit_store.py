# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""File-native net Manual Edit Buffer for frontend Project commits.

The Buffer is context for the next Agent request, not an operation log.  It
therefore keeps only the first unconsumed ``before`` and latest ``after`` for
each Project target.  Consumption atomically renames the current Buffer to a
consumer-specific receipt, making retries durable without SQLite.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import stat
from typing import Any
from uuid import uuid4

from pydantic import Field, model_validator

from .atomic_store import (
    AtomicJsonRecordStore,
    durable_unlink,
    fsync_directory,
)
from .errors import RuntimeFileError, RuntimeFileValidationError
from .locking import CrossProcessFileLock
from .models import (
    AwareDatetime,
    ProjectChange,
    ProjectChangeKind,
    StrictRuntimeModel,
    utc_now,
)
from .path_safety import hashed_runtime_segment, require_safe_runtime_segment


class ManualEditStoreError(RuntimeFileError):
    """Base error for file-native Manual Edit Buffer operations."""


class ManualEditProjectNotFound(ManualEditStoreError):
    pass


class ManualEditGenerationConflict(ManualEditStoreError):
    pass


class ManualEditChangeConflict(ManualEditStoreError):
    pass


class ManualEditIntegrityError(ManualEditStoreError):
    pass


class UnsafeManualEditPath(ManualEditStoreError, ValueError):
    pass


class ManualEditBuffer(StrictRuntimeModel):
    buffer_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    base_generation: int = Field(ge=0)
    head_generation: int = Field(ge=0)
    head: int = Field(ge=1)
    changes: list[ProjectChange] = Field(min_length=1)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_net_buffer(self) -> ManualEditBuffer:
        if self.head_generation <= self.base_generation:
            raise ValueError(
                "Manual Edit Buffer head generation must follow its base",
            )
        keys = [_change_key(change) for change in self.changes]
        if len(keys) != len(set(keys)):
            raise ValueError("Manual Edit Buffer has duplicate change targets")
        if any(
            change.before_hash == change.after_hash for change in self.changes
        ):
            raise ValueError(
                "Manual Edit Buffer cannot persist a zero-net change",
            )
        return self


@dataclass(frozen=True, slots=True)
class ManualEditConsumption:
    buffer: ManualEditBuffer
    consumer_id: str
    replayed: bool


ChangeInput = ProjectChange | Mapping[str, Any]


class ManualEditBufferStore:
    """Maintain one unconsumed baseline-to-current Buffer per Project."""

    def __init__(
        self,
        data_root: str | os.PathLike[str],
        *,
        lock_timeout_seconds: float | None = 10.0,
    ) -> None:
        raw_root = Path(data_root).expanduser()
        if not raw_root.is_absolute():
            raise UnsafeManualEditPath(
                "Manual Edit data root must be absolute",
            )
        if lock_timeout_seconds is not None and lock_timeout_seconds < 0:
            raise ValueError("lock timeout must be non-negative or None")
        raw_root.mkdir(parents=True, exist_ok=True)
        self.data_root = raw_root.resolve(strict=True)
        if not self.data_root.is_dir():
            raise UnsafeManualEditPath(
                "Manual Edit data root must be a directory",
            )
        self.lock_timeout_seconds = lock_timeout_seconds

    def record_frontend_commit(
        self,
        project_id: str,
        *,
        base_generation: int,
        head_generation: int,
        changes: Sequence[ChangeInput],
        _lifecycle_lock_held: bool = False,
    ) -> ManualEditBuffer | None:
        """Merge one frontend commit into the unconsumed net Buffer.

        Calls must follow Project generation order.  For a target already in
        the Buffer, the incoming ``before_hash`` must equal the Buffer's latest
        ``after_hash``.  This rejects gaps and unrelated payloads even when the
        caller supplies otherwise plausible generation numbers.
        """

        project_id = self._safe_project_id(project_id)
        if base_generation < 0:
            raise ValueError("base_generation cannot be negative")
        if head_generation <= base_generation:
            raise ValueError(
                "head_generation must be greater than base_generation",
            )
        incoming = [ProjectChange.model_validate(item) for item in changes]
        _require_unique_changes(incoming)
        with self._lock(
            project_id,
            lifecycle_lock_held=_lifecycle_lock_held,
        ):
            existing = self._read_unlocked(project_id)
            if (
                existing is not None
                and existing.head_generation == head_generation
            ):
                # Recovery may replay a commit after the Buffer write but
                # before the enclosing Project journal was finalized.
                return existing
            if (
                existing is not None
                and existing.head_generation != base_generation
            ):
                raise ManualEditGenerationConflict(
                    "Manual Edit commit does not continue the Buffer head: "
                    f"expected base={existing.head_generation}, "
                    f"actual base={base_generation}",
                )
            merged = _merge_changes(
                existing.changes if existing is not None else (),
                incoming,
            )
            if not merged:
                if existing is not None:
                    durable_unlink(self._buffer_path(project_id))
                return None

            now = utc_now()
            buffer = ManualEditBuffer(
                buffer_id=(
                    existing.buffer_id
                    if existing is not None
                    else f"manual-buffer-{uuid4().hex}"
                ),
                project_id=project_id,
                base_generation=(
                    existing.base_generation
                    if existing is not None
                    else base_generation
                ),
                head_generation=head_generation,
                head=existing.head + 1 if existing is not None else 1,
                changes=merged,
                created_at=existing.created_at
                if existing is not None
                else now,
                updated_at=now,
            )
            self._buffer_store(project_id).write(buffer)
            return buffer

    def reconcile_non_frontend_commit(
        self,
        project_id: str,
        *,
        base_generation: int,
        head_generation: int,
        changes: Sequence[ChangeInput],
        _lifecycle_lock_held: bool = False,
    ) -> ManualEditBuffer | None:
        """Advance the Buffer across Agent/Runtime commits.

        Unrelated user edits stay available as context.  Any buffered target
        touched by a later non-frontend writer is removed because it no longer
        describes a user-authored baseline-to-current value.
        """

        project_id = self._safe_project_id(project_id)
        incoming = [ProjectChange.model_validate(item) for item in changes]
        _require_unique_changes(incoming)
        with self._lock(
            project_id,
            lifecycle_lock_held=_lifecycle_lock_held,
        ):
            existing = self._read_unlocked(project_id)
            if existing is None:
                return None
            if existing.head_generation == head_generation:
                return existing
            if existing.head_generation != base_generation:
                raise ManualEditGenerationConflict(
                    "Non-frontend commit does not continue the Buffer head: "
                    f"expected base={existing.head_generation}, "
                    f"actual base={base_generation}",
                )
            retained = [
                buffered
                for buffered in existing.changes
                if not any(
                    _changes_overlap(buffered, change) for change in incoming
                )
            ]
            if not retained:
                durable_unlink(self._buffer_path(project_id))
                return None
            updated = ManualEditBuffer(
                buffer_id=existing.buffer_id,
                project_id=project_id,
                base_generation=existing.base_generation,
                head_generation=head_generation,
                head=existing.head + 1,
                changes=retained,
                created_at=existing.created_at,
                updated_at=utc_now(),
            )
            self._buffer_store(project_id).write(updated)
            return updated

    def read(self, project_id: str) -> ManualEditBuffer | None:
        project_id = self._safe_project_id(project_id)
        with self._lock(project_id):
            return self._read_unlocked(project_id)

    def consume(
        self,
        project_id: str,
        *,
        consumer_id: str,
    ) -> ManualEditConsumption | None:
        """Atomically take the current Buffer once for ``consumer_id``.

        The receipt is the exact Pydantic Buffer JSON moved from the authority
        path.  A retry by the same consumer reads that receipt and never takes a
        later Buffer created for another Agent request.
        """

        project_id = self._safe_project_id(project_id)
        if not isinstance(consumer_id, str) or not consumer_id:
            raise ValueError("consumer_id cannot be empty")
        receipt_path = self._receipt_path(project_id, consumer_id)
        with self._lock(project_id):
            receipt = AtomicJsonRecordStore(
                receipt_path,
                ManualEditBuffer,
            ).read_or_none()
            if receipt is not None:
                self._assert_identity(receipt, project_id)
                return ManualEditConsumption(
                    buffer=receipt,
                    consumer_id=consumer_id,
                    replayed=True,
                )

            current = self._read_unlocked(project_id)
            if current is None:
                return None
            receipt_root = receipt_path.parent
            receipt_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            manual_root = self._manual_root(project_id)
            fsync_directory(manual_root)
            if receipt_path.exists():
                raise ManualEditIntegrityError(
                    "Manual Edit receipt appeared while holding its lock",
                )
            os.rename(self._buffer_path(project_id), receipt_path)
            fsync_directory(receipt_root)
            fsync_directory(manual_root)
            return ManualEditConsumption(
                buffer=current,
                consumer_id=consumer_id,
                replayed=False,
            )

    def receipt_path(self, project_id: str, consumer_id: str) -> Path:
        project_id = self._safe_project_id(project_id)
        if not isinstance(consumer_id, str) or not consumer_id:
            raise ValueError("consumer_id cannot be empty")
        return self._receipt_path(project_id, consumer_id)

    def _read_unlocked(self, project_id: str) -> ManualEditBuffer | None:
        buffer = self._buffer_store(project_id).read_or_none()
        if buffer is not None:
            self._assert_identity(buffer, project_id)
        return buffer

    @staticmethod
    def _assert_identity(buffer: ManualEditBuffer, project_id: str) -> None:
        if buffer.project_id != project_id:
            raise ManualEditIntegrityError(
                "Manual Edit Buffer belongs to another Project",
            )

    def _safe_project_id(self, project_id: str) -> str:
        try:
            safe_id = require_safe_runtime_segment(
                project_id,
                label="project_id",
            )
        except RuntimeFileValidationError as exc:
            raise UnsafeManualEditPath(
                "project_id must be a safe filesystem identifier",
            ) from exc
        self._require_project(safe_id)
        return safe_id

    def _require_project(self, project_id: str) -> Path:
        project_root = self.data_root / project_id
        try:
            root_stat = project_root.lstat()
            project_stat = (project_root / "project.json").lstat()
        except FileNotFoundError as exc:
            raise ManualEditProjectNotFound(
                f"Project does not exist: {project_id}",
            ) from exc
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(
            root_stat.st_mode,
        ):
            raise UnsafeManualEditPath(
                "Project root must be a regular, non-symlink directory",
            )
        if stat.S_ISLNK(project_stat.st_mode) or not stat.S_ISREG(
            project_stat.st_mode,
        ):
            raise UnsafeManualEditPath(
                "project.json must be a regular, non-symlink file",
            )
        return project_root

    def _runtime_root(self, project_id: str) -> Path:
        return self.data_root / project_id / "runtime"

    def _manual_root(self, project_id: str) -> Path:
        return self._runtime_root(project_id) / "manual-edit"

    def _buffer_path(self, project_id: str) -> Path:
        return self._manual_root(project_id) / "buffer.json"

    def _receipt_path(self, project_id: str, consumer_id: str) -> Path:
        name = hashed_runtime_segment("consumer", consumer_id)
        return self._manual_root(project_id) / "consumed" / f"{name}.json"

    def _buffer_store(
        self,
        project_id: str,
    ) -> AtomicJsonRecordStore[ManualEditBuffer]:
        return AtomicJsonRecordStore(
            self._buffer_path(project_id),
            ManualEditBuffer,
        )

    @contextmanager
    def _lock(self, project_id: str, *, lifecycle_lock_held: bool = False):
        if lifecycle_lock_held:
            with CrossProcessFileLock(
                self._runtime_root(project_id)
                / "locks"
                / "manual-edit-buffer.lock",
                timeout_seconds=self.lock_timeout_seconds,
            ):
                yield
            return
        with CrossProcessFileLock(
            self.data_root / ".locks" / f"project-{project_id}.lock",
            timeout_seconds=self.lock_timeout_seconds,
        ):
            self._require_project(project_id)
            with CrossProcessFileLock(
                self._runtime_root(project_id)
                / "locks"
                / "manual-edit-buffer.lock",
                timeout_seconds=self.lock_timeout_seconds,
            ):
                yield


def _change_key(change: ProjectChange) -> str:
    if change.json_pointer is not None:
        return f"pointer:{change.json_pointer}"
    if change.file_id is not None:
        return f"file:{change.file_id}"
    if change.target_ref is not None:
        return f"target:{change.target_ref}"
    raise ManualEditIntegrityError("ProjectChange has no durable locator")


def _require_unique_changes(changes: Sequence[ProjectChange]) -> None:
    keys = [_change_key(change) for change in changes]
    if len(keys) != len(set(keys)):
        raise ManualEditChangeConflict(
            "One frontend commit contains duplicate change targets",
        )


def _merge_changes(
    previous: Sequence[ProjectChange],
    incoming: Sequence[ProjectChange],
) -> list[ProjectChange]:
    accumulated = {_change_key(change): change for change in previous}
    if len(accumulated) != len(previous):
        raise ManualEditIntegrityError(
            "Stored Manual Edit Buffer has duplicate change targets",
        )
    for change in incoming:
        key = _change_key(change)
        prior = accumulated.get(key)
        if prior is None:
            if change.before_hash != change.after_hash:
                accumulated[key] = change
            continue
        if prior.after_hash != change.before_hash:
            raise ManualEditChangeConflict(
                "Frontend change does not continue buffered target state: "
                f"{key} expected before={prior.after_hash!r}, "
                f"actual before={change.before_hash!r}",
            )
        if prior.before_hash == change.after_hash:
            accumulated.pop(key)
            continue
        accumulated[key] = ProjectChange(
            kind=_merged_kind(prior.kind, change.kind),
            json_pointer=change.json_pointer or prior.json_pointer,
            file_id=change.file_id or prior.file_id,
            target_ref=change.target_ref or prior.target_ref,
            before_hash=prior.before_hash,
            after_hash=change.after_hash,
            before=prior.before,
            after=change.after,
        )
    return [accumulated[key] for key in sorted(accumulated)]


def _merged_kind(
    previous: ProjectChangeKind,
    incoming: ProjectChangeKind,
) -> ProjectChangeKind:
    if previous is ProjectChangeKind.CREATE:
        return ProjectChangeKind.CREATE
    if incoming is ProjectChangeKind.DELETE:
        return ProjectChangeKind.DELETE
    if (
        previous is ProjectChangeKind.DELETE
        and incoming is ProjectChangeKind.CREATE
    ):
        return ProjectChangeKind.UPDATE
    if incoming in {
        ProjectChangeKind.MOVE,
        ProjectChangeKind.REORDER,
        ProjectChangeKind.SELECT_ASSET,
    }:
        return incoming
    if previous in {
        ProjectChangeKind.MOVE,
        ProjectChangeKind.REORDER,
        ProjectChangeKind.SELECT_ASSET,
    }:
        return previous
    return ProjectChangeKind.UPDATE


def _changes_overlap(left: ProjectChange, right: ProjectChange) -> bool:
    if left.json_pointer is not None and right.json_pointer is not None:
        from .field_blocks import pointers_overlap

        return pointers_overlap(left.json_pointer, right.json_pointer)
    if left.file_id is not None and right.file_id is not None:
        return left.file_id == right.file_id
    if left.target_ref is not None and right.target_ref is not None:
        return left.target_ref == right.target_ref
    return False


__all__ = [
    "ManualEditBuffer",
    "ManualEditBufferStore",
    "ManualEditChangeConflict",
    "ManualEditConsumption",
    "ManualEditGenerationConflict",
    "ManualEditIntegrityError",
    "ManualEditProjectNotFound",
    "ManualEditStoreError",
    "UnsafeManualEditPath",
]
