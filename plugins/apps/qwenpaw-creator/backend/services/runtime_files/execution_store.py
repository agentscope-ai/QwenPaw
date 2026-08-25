# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=redefined-builtin,too-many-public-methods
# pylint: disable=use-sequence-for-iteration
"""File-native SpecialistRun, Task, authorization and quarantine storage.

The store is deliberately independent from the legacy SQL Runtime.  Mutable
entity heads use atomic Pydantic JSON with checksum CAS; ordered attempts,
messages and continuations use durable append-only JSONL. Every mutating
operation holds the short Execution-domain Runtime lock. Session and Agent Run
state use separate domain locks, while Project deletion remains ordered by the
shared lifecycle lock. Provider/model calls must happen outside these locks.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import logging
import os
from pathlib import Path
import secrets
import stat
from typing import Any, TypeVar
from uuid import uuid4

from domain.enums import (
    TERMINAL_SPECIALIST_STATUSES,
    SpecialistRunStatus,
    TaskStatus,
)

from .atomic_store import AtomicJsonRecordStore, RecordSnapshot
from .errors import RuntimeFileError
from .execution_models import (
    ContinuationState,
    ExecutionAuthorizationRecord,
    ExecutionAuthorizationStatus,
    QuarantinedTaskResult,
    SpecialistContinuationEvent,
    SpecialistMessageRecord,
    SpecialistRunRecord,
    TERMINAL_TASK_ATTEMPT_STATUSES,
    TaskAttemptEvent,
    TaskAttemptStatus,
    TaskRecord,
    TraceableExecutionRecord,
)
from .jsonl_store import DurableJsonlStore
from .locking import CrossProcessFileLock
from .models import ReviewPolicy, utc_now
from .path_safety import require_safe_runtime_segment

logger = logging.getLogger("qwenpaw.creator.runtime_files.execution_store")


def _log_safe(value: object) -> str:
    """Neutralise CR/LF so identifier values cannot forge log lines."""
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


class ExecutionStoreError(RuntimeFileError):
    """Base error for the file-native execution aggregate."""


class UnsafeExecutionPath(ExecutionStoreError, ValueError):
    pass


class ExecutionStateConflict(ExecutionStoreError):
    pass


class ExecutionPayloadConflict(ExecutionStoreError):
    pass


class ExecutionStoreIntegrityError(ExecutionStoreError):
    pass


class AuthorizationTokenConflict(ExecutionStateConflict):
    pass


@dataclass(frozen=True, slots=True)
class QuarantineWriteResult:
    record: QuarantinedTaskResult
    task: TaskRecord
    replayed: bool


_RUN_TRANSITIONS: dict[SpecialistRunStatus, frozenset[SpecialistRunStatus]] = {
    SpecialistRunStatus.QUEUED: frozenset(
        {
            SpecialistRunStatus.QUEUED_CAPACITY,
            SpecialistRunStatus.RUNNING_MODEL,
            SpecialistRunStatus.FAILED,
            SpecialistRunStatus.STALE,
            SpecialistRunStatus.CANCELLED,
        },
    ),
    SpecialistRunStatus.QUEUED_CAPACITY: frozenset(
        {
            SpecialistRunStatus.QUEUED,
            SpecialistRunStatus.RUNNING_MODEL,
            SpecialistRunStatus.FAILED,
            SpecialistRunStatus.STALE,
            SpecialistRunStatus.CANCELLED,
        },
    ),
    SpecialistRunStatus.RUNNING_MODEL: frozenset(
        {
            SpecialistRunStatus.WAITING_RUNTIME,
            SpecialistRunStatus.WAITING_AUTHORIZATION,
            SpecialistRunStatus.SUCCEEDED,
            SpecialistRunStatus.BLOCKED,
            SpecialistRunStatus.FAILED,
            SpecialistRunStatus.STALE,
            SpecialistRunStatus.CANCELLED,
        },
    ),
    SpecialistRunStatus.WAITING_RUNTIME: frozenset(
        {
            SpecialistRunStatus.RUNNING_MODEL,
            SpecialistRunStatus.SUCCEEDED,
            SpecialistRunStatus.BLOCKED,
            SpecialistRunStatus.FAILED,
            SpecialistRunStatus.STALE,
            SpecialistRunStatus.CANCELLED,
        },
    ),
    SpecialistRunStatus.WAITING_AUTHORIZATION: frozenset(
        {
            SpecialistRunStatus.RUNNING_MODEL,
            SpecialistRunStatus.BLOCKED,
            SpecialistRunStatus.FAILED,
            SpecialistRunStatus.STALE,
            SpecialistRunStatus.CANCELLED,
        },
    ),
}

_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.QUEUED: frozenset(
        {
            TaskStatus.RUNNING,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.QUARANTINED,
        },
    ),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.QUARANTINED,
        },
    ),
    # The durable Task identity and request fingerprint stay fixed across an
    # explicitly authorized retry; only a FAILED Task may reopen as QUEUED.
    TaskStatus.FAILED: frozenset({TaskStatus.QUEUED}),
    # A once-valid result may become unimportable after a crash/revalidation.
    TaskStatus.SUCCEEDED: frozenset({TaskStatus.QUARANTINED}),
}

_RUN_IMMUTABLE_FIELDS = frozenset(
    {
        "run_id",
        "project_id",
        "round_id",
        "role",
        "input_generation",
        "input_etag",
        "created_at",
        "caused_by_request_id",
        "caused_by_message_id",
        "caused_by_message_seq",
        "review_policy",
    },
)
_TASK_IMMUTABLE_FIELDS = frozenset(
    {
        "task_id",
        "project_id",
        "round_id",
        "run_id",
        "kind",
        "request_fingerprint",
        "idempotency_key",
        "input_generation",
        "input_etag",
        "expected_target_version",
        "input_refs",
        "read_set",
        "created_at",
        "caused_by_request_id",
        "caused_by_message_id",
        "caused_by_message_seq",
        "review_policy",
    },
)

E = TypeVar("E")


class ProjectExecutionStore:
    """Project-scoped file store for execution state and audit streams."""

    def __init__(
        self,
        data_root: str | os.PathLike[str],
        *,
        lock_timeout_seconds: float | None = 10.0,
    ) -> None:
        raw_root = Path(data_root).expanduser()
        if not raw_root.is_absolute():
            raise UnsafeExecutionPath("Runtime data root must be absolute")
        if lock_timeout_seconds is not None and lock_timeout_seconds < 0:
            raise ValueError("lock timeout must be non-negative or None")
        raw_root.mkdir(parents=True, exist_ok=True)
        self.data_root = raw_root.resolve(strict=True)
        if not self.data_root.is_dir():
            raise UnsafeExecutionPath("Runtime data root must be a directory")
        self.lock_timeout_seconds = lock_timeout_seconds

    # -- current SpecialistRun state -------------------------------------

    def create_specialist_run(
        self,
        record: SpecialistRunRecord | Mapping[str, Any],
    ) -> SpecialistRunRecord:
        candidate = SpecialistRunRecord.model_validate(record)
        project_id = self._safe(candidate.project_id, "project_id")
        run_id = self._safe(candidate.run_id, "run_id")
        self._safe(candidate.round_id, "round_id")
        self._validate_optional_ids(
            related_run_id=candidate.related_run_id,
            supersedes_run_id=candidate.supersedes_run_id,
            caused_by_request_id=candidate.caused_by_request_id,
            caused_by_message_id=candidate.caused_by_message_id,
        )
        if candidate.status not in {
            SpecialistRunStatus.QUEUED,
            SpecialistRunStatus.QUEUED_CAPACITY,
        }:
            raise ExecutionStateConflict(
                "new SpecialistRun must start QUEUED or QUEUED_CAPACITY",
            )
        if candidate.last_continuation_seq != 0:
            raise ExecutionStateConflict(
                "new SpecialistRun continuation head must start at zero",
            )
        self._require_project(project_id)
        with self._project_lock(project_id):
            store = self._run_store(project_id, run_id)
            created = store.try_create(candidate)
            if created is not None:
                return created.value
            existing = store.read()
            self._assert_run_identity(existing, project_id, run_id)
            if self._equivalent(existing, candidate):
                return existing
            raise ExecutionPayloadConflict(
                f"SpecialistRun already exists with different payload: {run_id}",
            )

    create_run = create_specialist_run

    def get_specialist_run(
        self,
        project_id: str,
        run_id: str,
    ) -> SpecialistRunRecord:
        project_id, run_id = self._safe_project_child(
            project_id,
            run_id,
            child_label="run_id",
        )
        record = self._run_store(project_id, run_id).read()
        self._assert_run_identity(record, project_id, run_id)
        return record

    get_run = get_specialist_run

    def list_specialist_runs(
        self,
        project_id: str,
    ) -> list[SpecialistRunRecord]:
        """Return every durable Run head for one Project, newest first."""

        project_id = self._safe(project_id, "project_id")
        self._require_project(project_id)
        with self._project_lock_read(project_id):
            root = self._runtime_root(project_id) / "runs"
            if not root.exists():
                return []
            if root.is_symlink() or not root.is_dir():
                raise UnsafeExecutionPath(
                    "Runtime runs path must be a real directory",
                )
            records: list[SpecialistRunRecord] = []
            for child in root.iterdir():
                if child.is_symlink() or not child.is_dir():
                    raise UnsafeExecutionPath(
                        "Runtime runs directory contains an unsafe entry",
                    )
                run_id = self._safe(child.name, "run_id")
                record = self._run_store(project_id, run_id).read()
                self._assert_run_identity(record, project_id, run_id)
                records.append(record)
            return sorted(
                records,
                key=lambda item: item.updated_at,
                reverse=True,
            )

    def transition_specialist_run(
        self,
        project_id: str,
        run_id: str,
        *,
        expected_status: (
            SpecialistRunStatus | str | Collection[SpecialistRunStatus | str]
        ),
        status: SpecialistRunStatus | str,
        updates: Mapping[str, Any] | None = None,
        expected_checksum: str | None = None,
        updated_at: datetime | None = None,
    ) -> SpecialistRunRecord:
        project_id, run_id = self._safe_project_child(
            project_id,
            run_id,
            child_label="run_id",
        )
        expected = self._run_statuses(expected_status)
        target = SpecialistRunStatus(status)
        with self._project_lock(project_id):
            snapshot = self._run_store(project_id, run_id).read_snapshot()
            self._assert_run_identity(snapshot.value, project_id, run_id)
            return self._transition_run_unlocked(
                project_id,
                run_id,
                snapshot,
                expected=expected,
                target=target,
                updates=updates,
                expected_checksum=expected_checksum,
                updated_at=updated_at,
            )

    transition_run = transition_specialist_run

    # -- SpecialistRun streams ------------------------------------------

    def append_specialist_message(
        self,
        project_id: str,
        run_id: str,
        *,
        message_id: str,
        role: str,
        content_parts: Sequence[Any],
        provider_message_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        caused_by_request_id: str | None = None,
        caused_by_message_id: str | None = None,
        caused_by_message_seq: int | None = None,
        review_policy: ReviewPolicy | str | None = None,
        created_at: datetime | None = None,
    ) -> SpecialistMessageRecord:
        project_id, run_id = self._safe_project_child(
            project_id,
            run_id,
            child_label="run_id",
        )
        message_id = self._safe(message_id, "message_id")
        self._validate_optional_ids(
            caused_by_request_id=caused_by_request_id,
            caused_by_message_id=caused_by_message_id,
        )
        with self._project_lock(project_id):
            run = self._run_store(project_id, run_id).read()
            self._assert_run_identity(run, project_id, run_id)
            stream = self._messages_store(project_id, run_id)
            records = stream.read_records()
            existing = next(
                (item for item in records if item.message_id == message_id),
                None,
            )
            provenance = self._provenance(
                run,
                caused_by_request_id=caused_by_request_id,
                caused_by_message_id=caused_by_message_id,
                caused_by_message_seq=caused_by_message_seq,
                review_policy=review_policy,
            )
            candidate = SpecialistMessageRecord(
                message_id=message_id,
                project_id=project_id,
                run_id=run_id,
                message_seq=(
                    existing.message_seq if existing else len(records) + 1
                ),
                role=role,
                content_parts=list(content_parts),
                provider_message_id=provider_message_id,
                metadata=dict(metadata or {}),
                created_at=(
                    existing.created_at
                    if existing
                    else (created_at or utc_now())
                ),
                **provenance,
            )
            if existing is not None:
                if existing == candidate:
                    return existing
                raise ExecutionPayloadConflict(
                    f"message_id was reused with different payload: {message_id}",
                )
            stream.append(candidate, expected_next_seq=candidate.message_seq)
            return candidate

    append_message = append_specialist_message

    def list_specialist_messages(
        self,
        project_id: str,
        run_id: str,
    ) -> list[SpecialistMessageRecord]:
        project_id, run_id = self._safe_project_child(
            project_id,
            run_id,
            child_label="run_id",
        )
        self._assert_run_identity(
            self._run_store(project_id, run_id).read(),
            project_id,
            run_id,
        )
        records = self._messages_store(project_id, run_id).read_records()
        self._assert_stream_ownership(
            records,
            project_id=project_id,
            run_id=run_id,
        )
        return records

    list_messages = list_specialist_messages

    def append_continuation_event(
        self,
        project_id: str,
        run_id: str,
        *,
        event_id: str,
        continuation_id: str,
        continuation_token: str,
        state: ContinuationState | str,
        task_id: str | None = None,
        request: Mapping[str, Any] | None = None,
        result: Mapping[str, Any] | None = None,
        caused_by_request_id: str | None = None,
        caused_by_message_id: str | None = None,
        caused_by_message_seq: int | None = None,
        review_policy: ReviewPolicy | str | None = None,
        created_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> SpecialistContinuationEvent:
        project_id, run_id = self._safe_project_child(
            project_id,
            run_id,
            child_label="run_id",
        )
        event_id = self._safe(event_id, "event_id")
        continuation_id = self._safe(continuation_id, "continuation_id")
        if task_id is not None:
            task_id = self._safe(task_id, "task_id")
        if not continuation_token:
            raise ValueError("continuation_token cannot be empty")
        target_state = ContinuationState(state)
        now = created_at or utc_now()
        with self._project_lock(project_id):
            run_store = self._run_store(project_id, run_id)
            run_snapshot = run_store.read_snapshot()
            run = run_snapshot.value
            self._assert_run_identity(run, project_id, run_id)
            stream = self._continuations_store(project_id, run_id)
            records = stream.read_records()
            existing = next(
                (item for item in records if item.event_id == event_id),
                None,
            )
            history = [
                item
                for item in records
                if item.continuation_id == continuation_id
            ]
            if any(
                item.continuation_token == continuation_token
                and item.continuation_id != continuation_id
                for item in records
            ):
                raise ExecutionPayloadConflict(
                    "continuation_token is already owned by another continuation",
                )
            if history:
                first = history[0]
                if first.continuation_token != continuation_token:
                    raise ExecutionPayloadConflict(
                        "continuation token cannot change",
                    )
                if task_id is not None and first.task_id != task_id:
                    raise ExecutionPayloadConflict(
                        "continuation task cannot change",
                    )
                task_id = first.task_id
                normalized_request = dict(request or first.request)
            else:
                normalized_request = dict(request or {})
            provenance = self._provenance(
                run,
                caused_by_request_id=caused_by_request_id,
                caused_by_message_id=caused_by_message_id,
                caused_by_message_seq=caused_by_message_seq,
                review_policy=review_policy,
            )
            terminal = target_state in {
                ContinuationState.COMPLETED,
                ContinuationState.CANCELLED,
            }
            candidate = SpecialistContinuationEvent(
                event_id=event_id,
                continuation_id=continuation_id,
                project_id=project_id,
                run_id=run_id,
                task_id=task_id,
                continuation_seq=(
                    existing.continuation_seq
                    if existing is not None
                    else len(records) + 1
                ),
                continuation_token=continuation_token,
                state=target_state,
                request=normalized_request,
                result=dict(result) if result is not None else None,
                created_at=(existing.created_at if existing else now),
                completed_at=(
                    existing.completed_at
                    if existing is not None
                    else ((completed_at or now) if terminal else None)
                ),
                **provenance,
            )
            if existing is not None:
                if existing == candidate:
                    if (
                        existing is records[-1]
                        and run.last_continuation_seq
                        < existing.continuation_seq
                    ):
                        self._apply_continuation_head_unlocked(
                            project_id,
                            run_id,
                            run_snapshot,
                            existing,
                        )
                    return existing
                raise ExecutionPayloadConflict(
                    f"continuation event id was reused: {event_id}",
                )
            self._validate_continuation_transition(
                history,
                target_state=target_state,
            )
            self._validate_run_for_continuation(run, target_state=target_state)
            if task_id is not None:
                task = self._task_store(project_id, task_id).read()
                self._assert_task_identity(task, project_id, task_id)
                if task.run_id != run_id:
                    raise ExecutionStoreIntegrityError(
                        "continuation Task belongs to another SpecialistRun",
                    )
            stream.append(
                candidate,
                expected_next_seq=candidate.continuation_seq,
            )
            self._apply_continuation_head_unlocked(
                project_id,
                run_id,
                run_snapshot,
                candidate,
            )
            return candidate

    append_continuation = append_continuation_event

    def list_continuation_events(
        self,
        project_id: str,
        run_id: str,
    ) -> list[SpecialistContinuationEvent]:
        project_id, run_id = self._safe_project_child(
            project_id,
            run_id,
            child_label="run_id",
        )
        self._assert_run_identity(
            self._run_store(project_id, run_id).read(),
            project_id,
            run_id,
        )
        records = self._continuations_store(project_id, run_id).read_records()
        self._assert_stream_ownership(
            records,
            project_id=project_id,
            run_id=run_id,
        )
        return records

    # -- current Task state and attempts --------------------------------

    def create_task(
        self,
        record: TaskRecord | Mapping[str, Any],
    ) -> TaskRecord:
        candidate = TaskRecord.model_validate(record)
        project_id = self._safe(candidate.project_id, "project_id")
        task_id = self._safe(candidate.task_id, "task_id")
        self._validate_optional_ids(
            round_id=candidate.round_id,
            run_id=candidate.run_id,
            caused_by_request_id=candidate.caused_by_request_id,
            caused_by_message_id=candidate.caused_by_message_id,
        )
        if candidate.status is not TaskStatus.QUEUED:
            raise ExecutionStateConflict("new Task must start QUEUED")
        if candidate.last_attempt_seq != 0:
            raise ExecutionStateConflict(
                "new Task Attempt head must start at zero",
            )
        self._require_project(project_id)
        with self._project_lock(project_id):
            if candidate.run_id is not None:
                run = self._run_store(project_id, candidate.run_id).read()
                self._assert_run_identity(run, project_id, candidate.run_id)
                if run.status in TERMINAL_SPECIALIST_STATUSES:
                    raise ExecutionStateConflict(
                        "terminal SpecialistRun cannot admit a new Task",
                    )
                if candidate.round_id != run.round_id:
                    raise ExecutionStoreIntegrityError(
                        "Task round_id does not match its SpecialistRun",
                    )
                self._assert_provenance_inherits(candidate, run)
            store = self._task_store(project_id, task_id)
            created = store.try_create(candidate)
            if created is not None:
                logger.info(
                    "task created: project=%s task=%s kind=%s run=%s status=%s",
                    project_id,
                    task_id,
                    candidate.kind.value,
                    candidate.run_id,
                    candidate.status.value,
                )
                return created.value
            existing = store.read()
            self._assert_task_identity(existing, project_id, task_id)
            if self._equivalent(existing, candidate):
                logger.debug(
                    "task already exists (idempotent): project=%s task=%s",
                    project_id,
                    task_id,
                )
                return existing
            raise ExecutionPayloadConflict(
                f"Task already exists with different payload: {task_id}",
            )

    def get_task(
        self,
        project_id: str,
        task_id: str,
        *,
        _lifecycle_lock_held: bool = False,
    ) -> TaskRecord:
        project_id, task_id = self._safe_project_child(
            project_id,
            task_id,
            child_label="task_id",
        )
        with self._project_lock(
            project_id,
            _lifecycle_lock_held=_lifecycle_lock_held,
        ):
            record = self._task_store(project_id, task_id).read()
            self._assert_task_identity(record, project_id, task_id)
            return record

    def list_tasks(self, project_id: str) -> list[TaskRecord]:
        """Return every durable Task head for one Project, newest first."""

        project_id = self._safe(project_id, "project_id")
        self._require_project(project_id)
        with self._project_lock_read(project_id):
            root = self._runtime_root(project_id) / "tasks"
            if not root.exists():
                return []
            if root.is_symlink() or not root.is_dir():
                raise UnsafeExecutionPath(
                    "Runtime tasks path must be a real directory",
                )
            records: list[TaskRecord] = []
            for child in root.iterdir():
                if child.is_symlink() or not child.is_dir():
                    raise UnsafeExecutionPath(
                        "Runtime tasks directory contains an unsafe entry",
                    )
                task_id = self._safe(child.name, "task_id")
                record = self._task_store(project_id, task_id).read()
                self._assert_task_identity(record, project_id, task_id)
                records.append(record)
            return sorted(
                records,
                key=lambda item: item.updated_at,
                reverse=True,
            )

    def transition_task(
        self,
        project_id: str,
        task_id: str,
        *,
        expected_status: TaskStatus | str | Collection[TaskStatus | str],
        status: TaskStatus | str,
        updates: Mapping[str, Any] | None = None,
        expected_checksum: str | None = None,
        updated_at: datetime | None = None,
        _lifecycle_lock_held: bool = False,
    ) -> TaskRecord:
        project_id, task_id = self._safe_project_child(
            project_id,
            task_id,
            child_label="task_id",
        )
        expected = self._task_statuses(expected_status)
        target = TaskStatus(status)
        with self._project_lock(
            project_id,
            _lifecycle_lock_held=_lifecycle_lock_held,
        ):
            snapshot = self._task_store(project_id, task_id).read_snapshot()
            self._assert_task_identity(snapshot.value, project_id, task_id)
            return self._transition_task_unlocked(
                project_id,
                task_id,
                snapshot,
                expected=expected,
                target=target,
                updates=updates,
                expected_checksum=expected_checksum,
                updated_at=updated_at,
            )

    def append_task_attempt(
        self,
        project_id: str,
        task_id: str,
        *,
        event_id: str,
        attempt_id: str,
        status: TaskAttemptStatus | str,
        attempt_number: int | None = None,
        provider_task_id: str | None = None,
        input: Mapping[str, Any] | None = None,
        output: Mapping[str, Any] | None = None,
        output_refs: Sequence[str] = (),
        error: Mapping[str, Any] | None = None,
        caused_by_request_id: str | None = None,
        caused_by_message_id: str | None = None,
        caused_by_message_seq: int | None = None,
        review_policy: ReviewPolicy | str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        _lifecycle_lock_held: bool = False,
    ) -> TaskAttemptEvent:
        project_id, task_id = self._safe_project_child(
            project_id,
            task_id,
            child_label="task_id",
        )
        event_id = self._safe(event_id, "event_id")
        attempt_id = self._safe(attempt_id, "attempt_id")
        target_status = TaskAttemptStatus(status)
        now = utc_now()
        with self._project_lock(
            project_id,
            _lifecycle_lock_held=_lifecycle_lock_held,
        ):
            task_store = self._task_store(project_id, task_id)
            task_snapshot = task_store.read_snapshot()
            task = task_snapshot.value
            self._assert_task_identity(task, project_id, task_id)
            stream = self._attempts_store(project_id, task_id)
            records = stream.read_records()
            existing = next(
                (item for item in records if item.event_id == event_id),
                None,
            )
            history = [
                item for item in records if item.attempt_id == attempt_id
            ]
            max_attempt = max(
                (item.attempt_number for item in records),
                default=0,
            )
            if history:
                first = history[0]
                resolved_number = first.attempt_number
                if (
                    attempt_number is not None
                    and attempt_number != resolved_number
                ):
                    raise ExecutionPayloadConflict(
                        "attempt_number cannot change within an Attempt",
                    )
                if (
                    provider_task_id is not None
                    and first.provider_task_id is not None
                    and provider_task_id != first.provider_task_id
                ):
                    raise ExecutionPayloadConflict(
                        "provider_task_id cannot change within an Attempt",
                    )
                resolved_provider_id = (
                    provider_task_id or first.provider_task_id
                )
                resolved_input = (
                    dict(input) if input is not None else first.input
                )
                resolved_started_at = started_at or first.started_at
            else:
                resolved_number = attempt_number or (max_attempt + 1)
                if resolved_number != max_attempt + 1:
                    raise ExecutionStateConflict(
                        "a new Attempt must use the next contiguous attempt_number",
                    )
                resolved_provider_id = provider_task_id
                resolved_input = dict(input or {})
                resolved_started_at = started_at or now
            terminal = target_status in TERMINAL_TASK_ATTEMPT_STATUSES
            provenance = self._provenance(
                task,
                caused_by_request_id=caused_by_request_id,
                caused_by_message_id=caused_by_message_id,
                caused_by_message_seq=caused_by_message_seq,
                review_policy=review_policy,
            )
            candidate = TaskAttemptEvent(
                event_id=event_id,
                project_id=project_id,
                task_id=task_id,
                attempt_id=attempt_id,
                attempt_number=resolved_number,
                attempt_seq=(
                    existing.attempt_seq if existing else len(records) + 1
                ),
                status=target_status,
                provider_task_id=resolved_provider_id,
                input=resolved_input,
                output=dict(output) if output is not None else None,
                output_refs=list(output_refs),
                error=dict(error) if error is not None else None,
                started_at=resolved_started_at,
                finished_at=(
                    existing.finished_at
                    if existing is not None
                    else ((finished_at or now) if terminal else None)
                ),
                created_at=(existing.created_at if existing else now),
                **provenance,
            )
            if existing is not None:
                if existing == candidate:
                    if (
                        existing is records[-1]
                        and task.last_attempt_seq < existing.attempt_seq
                    ):
                        self._apply_attempt_head_unlocked(
                            project_id,
                            task_id,
                            task_snapshot,
                            existing,
                        )
                    return existing
                raise ExecutionPayloadConflict(
                    f"attempt event id was reused: {event_id}",
                )
            self._validate_attempt_transition(
                history,
                target_status=target_status,
            )
            required_task_status = (
                TaskStatus.QUEUED
                if target_status is TaskAttemptStatus.RUNNING
                else TaskStatus.RUNNING
            )
            if task.status is not required_task_status:
                raise ExecutionStateConflict(
                    "Task state does not admit this Attempt event: "
                    f"expected {required_task_status.value}, got {task.status.value}",
                )
            stream.append(candidate, expected_next_seq=candidate.attempt_seq)
            self._apply_attempt_head_unlocked(
                project_id,
                task_id,
                task_snapshot,
                candidate,
            )
            return candidate

    append_attempt = append_task_attempt

    def list_task_attempts(
        self,
        project_id: str,
        task_id: str,
    ) -> list[TaskAttemptEvent]:
        project_id, task_id = self._safe_project_child(
            project_id,
            task_id,
            child_label="task_id",
        )
        self._assert_task_identity(
            self._task_store(project_id, task_id).read(),
            project_id,
            task_id,
        )
        records = self._attempts_store(project_id, task_id).read_records()
        self._assert_stream_ownership(
            records,
            project_id=project_id,
            task_id=task_id,
        )
        return records

    list_attempts = list_task_attempts

    # -- execution authorization ----------------------------------------

    def create_execution_authorization(
        self,
        record: ExecutionAuthorizationRecord | Mapping[str, Any],
    ) -> ExecutionAuthorizationRecord:
        candidate = ExecutionAuthorizationRecord.model_validate(record)
        project_id = self._safe(candidate.project_id, "project_id")
        authorization_id = self._safe(
            candidate.authorization_id,
            "authorization_id",
        )
        self._safe(candidate.round_id, "round_id")
        self._safe(candidate.run_id, "run_id")
        self._validate_optional_ids(
            task_id=candidate.task_id,
            caused_by_request_id=candidate.caused_by_request_id,
            caused_by_message_id=candidate.caused_by_message_id,
        )
        self._require_project(project_id)
        with self._project_lock(project_id):
            for existing in self._authorization_records(project_id):
                if existing.authorization_id == authorization_id:
                    continue
                if secrets.compare_digest(
                    existing.authorization_token,
                    candidate.authorization_token,
                ):
                    raise ExecutionPayloadConflict(
                        "authorization_token is already owned by another request",
                    )
                if (
                    existing.execution_request_id
                    == candidate.execution_request_id
                ):
                    if self._authorization_request_signature(
                        existing,
                    ) == self._authorization_request_signature(candidate):
                        return existing
                    raise ExecutionPayloadConflict(
                        "execution_request_id was reused with a different request",
                    )
            store = self._authorization_store(project_id, authorization_id)
            created = store.try_create(candidate)
            if created is not None:
                return created.value
            existing = store.read()
            self._assert_authorization_identity(
                existing,
                project_id,
                authorization_id,
            )
            # authorization_id is derived deterministically from the
            # request, so identical retries replay the durable record:
            # compare the request signature, which ignores the per-call
            # random token and the decision lifecycle fields.
            if self._authorization_request_signature(
                existing,
            ) == self._authorization_request_signature(candidate):
                return existing
            raise ExecutionPayloadConflict(
                "authorization_id was reused with a different request",
            )

    create_authorization = create_execution_authorization

    def get_execution_authorization(
        self,
        project_id: str,
        authorization_id: str,
    ) -> ExecutionAuthorizationRecord:
        project_id, authorization_id = self._safe_project_child(
            project_id,
            authorization_id,
            child_label="authorization_id",
        )
        record = self._authorization_store(project_id, authorization_id).read()
        self._assert_authorization_identity(
            record,
            project_id,
            authorization_id,
        )
        return record

    get_authorization = get_execution_authorization

    def list_execution_authorizations(
        self,
        project_id: str,
    ) -> list[ExecutionAuthorizationRecord]:
        project_id = self._safe(project_id, "project_id")
        self._require_project(project_id)
        return sorted(
            self._authorization_records(project_id),
            key=lambda item: (item.created_at, item.authorization_id),
        )

    list_authorizations = list_execution_authorizations

    def get_authorization_snapshot(
        self,
        project_id: str,
        authorization_id: str,
    ) -> RecordSnapshot[ExecutionAuthorizationRecord]:
        project_id, authorization_id = self._safe_project_child(
            project_id,
            authorization_id,
            child_label="authorization_id",
        )
        snapshot = self._authorization_store(
            project_id,
            authorization_id,
        ).read_snapshot()
        self._assert_authorization_identity(
            snapshot.value,
            project_id,
            authorization_id,
        )
        return snapshot

    def decide_execution_authorization(
        self,
        project_id: str,
        authorization_id: str,
        *,
        authorization_token: str,
        status: ExecutionAuthorizationStatus | str,
        decision: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        expected_status: ExecutionAuthorizationStatus
        | str = (ExecutionAuthorizationStatus.PENDING),
        expected_checksum: str | None = None,
        decided_at: datetime | None = None,
    ) -> ExecutionAuthorizationRecord:
        project_id, authorization_id = self._safe_project_child(
            project_id,
            authorization_id,
            child_label="authorization_id",
        )
        target = ExecutionAuthorizationStatus(status)
        expected = ExecutionAuthorizationStatus(expected_status)
        if target is ExecutionAuthorizationStatus.PENDING:
            raise ExecutionStateConflict(
                "authorization decisions cannot target PENDING",
            )
        if not authorization_token:
            raise AuthorizationTokenConflict("authorization token is required")
        now = decided_at or utc_now()
        with self._project_lock(project_id):
            store = self._authorization_store(project_id, authorization_id)
            snapshot = store.read_snapshot()
            current = snapshot.value
            self._assert_authorization_identity(
                current,
                project_id,
                authorization_id,
            )
            if current.status is not expected:
                raise ExecutionStateConflict(
                    "authorization status CAS conflict: "
                    f"expected {expected.value}, got {current.status.value}",
                )
            if not secrets.compare_digest(
                current.authorization_token,
                authorization_token,
            ):
                raise AuthorizationTokenConflict(
                    "authorization token/status CAS failed",
                )
            if (
                target is ExecutionAuthorizationStatus.APPROVED
                and current.expires_at is not None
                and now >= current.expires_at
            ):
                raise ExecutionStateConflict(
                    "expired authorization cannot be approved",
                )
            if (
                target is ExecutionAuthorizationStatus.APPROVED
                and decision is None
            ):
                raise ExecutionStateConflict(
                    "APPROVED authorization requires a decision snapshot",
                )
            dumped = current.model_dump(mode="python")
            dumped.update(
                {
                    "status": target,
                    "decision": dict(decision)
                    if decision is not None
                    else None,
                    "metadata": {
                        **current.metadata,
                        **dict(metadata or {}),
                    },
                    "updated_at": now,
                    "decided_at": now,
                },
            )
            candidate = ExecutionAuthorizationRecord.model_validate(dumped)
            checksum = expected_checksum or snapshot.checksum
            return store.compare_and_swap(
                expected_checksum=checksum,
                value=candidate,
            ).value

    decide_authorization = decide_execution_authorization

    # -- late/stale result quarantine -----------------------------------

    def quarantine_task_result(
        self,
        project_id: str,
        task_id: str,
        *,
        reason: str,
        result: Mapping[str, Any],
        quarantine_id: str | None = None,
        request_fingerprint: str | None = None,
        input_generation: int | None = None,
        input_etag: str | None = None,
        input_refs: Sequence[str] | None = None,
        caused_by_request_id: str | None = None,
        caused_by_message_id: str | None = None,
        caused_by_message_seq: int | None = None,
        review_policy: ReviewPolicy | str | None = None,
        transition_task: bool = True,
        created_at: datetime | None = None,
    ) -> QuarantineWriteResult:
        project_id, task_id = self._safe_project_child(
            project_id,
            task_id,
            child_label="task_id",
        )
        quarantine_id = self._safe(
            quarantine_id or f"quarantine-{uuid4().hex}",
            "quarantine_id",
        )
        if not reason:
            raise ValueError("quarantine reason cannot be empty")
        with self._project_lock(project_id):
            task_store = self._task_store(project_id, task_id)
            task_snapshot = task_store.read_snapshot()
            task = task_snapshot.value
            self._assert_task_identity(task, project_id, task_id)
            provenance = self._provenance(
                task,
                caused_by_request_id=caused_by_request_id,
                caused_by_message_id=caused_by_message_id,
                caused_by_message_seq=caused_by_message_seq,
                review_policy=review_policy,
            )
            candidate = QuarantinedTaskResult(
                quarantine_id=quarantine_id,
                project_id=project_id,
                round_id=task.round_id,
                task_id=task_id,
                run_id=task.run_id,
                reason=reason,
                request_fingerprint=(
                    request_fingerprint or task.request_fingerprint
                ),
                input_generation=(
                    input_generation
                    if input_generation is not None
                    else task.input_generation
                ),
                input_etag=input_etag
                if input_etag is not None
                else task.input_etag,
                result=dict(result),
                input_refs=list(input_refs or task.input_refs),
                created_at=created_at or utc_now(),
                **provenance,
            )
            store = self._quarantine_store(project_id, task_id)
            created = store.try_create(candidate)
            replayed = created is None
            if replayed:
                existing = store.read()
                self._assert_quarantine_identity(existing, project_id, task_id)
                if not self._equivalent(
                    existing,
                    candidate,
                    ignored={"quarantine_id", "created_at"},
                ):
                    raise ExecutionPayloadConflict(
                        "Task already has a different quarantined result",
                    )
                candidate = existing
            if transition_task and task.status in {
                TaskStatus.QUEUED,
                TaskStatus.RUNNING,
                TaskStatus.SUCCEEDED,
            }:
                task = self._transition_task_unlocked(
                    project_id,
                    task_id,
                    task_snapshot,
                    expected={task.status},
                    target=TaskStatus.QUARANTINED,
                    updates={
                        "result": dict(result),
                        "error": {"quarantineReason": reason},
                    },
                )
            return QuarantineWriteResult(
                record=candidate,
                task=task,
                replayed=replayed,
            )

    def get_quarantined_task_result(
        self,
        project_id: str,
        task_id: str,
    ) -> QuarantinedTaskResult:
        project_id, task_id = self._safe_project_child(
            project_id,
            task_id,
            child_label="task_id",
        )
        record = self._quarantine_store(project_id, task_id).read()
        self._assert_quarantine_identity(record, project_id, task_id)
        return record

    get_quarantine_record = get_quarantined_task_result

    # -- transition internals -------------------------------------------

    def _apply_continuation_head_unlocked(
        self,
        project_id: str,
        run_id: str,
        snapshot: RecordSnapshot[SpecialistRunRecord],
        event: SpecialistContinuationEvent,
    ) -> SpecialistRunRecord:
        current = snapshot.value
        if current.last_continuation_seq >= event.continuation_seq:
            return current
        if current.last_continuation_seq + 1 != event.continuation_seq:
            raise ExecutionStoreIntegrityError(
                "SpecialistRun continuation head is not contiguous",
            )
        target_by_state = {
            ContinuationState.WAITING: SpecialistRunStatus.WAITING_RUNTIME,
            ContinuationState.RESUMED: SpecialistRunStatus.RUNNING_MODEL,
            ContinuationState.COMPLETED: SpecialistRunStatus.RUNNING_MODEL,
            ContinuationState.CANCELLED: SpecialistRunStatus.CANCELLED,
        }
        expected_by_state = {
            ContinuationState.WAITING: {SpecialistRunStatus.RUNNING_MODEL},
            ContinuationState.RESUMED: {SpecialistRunStatus.WAITING_RUNTIME},
            ContinuationState.COMPLETED: {SpecialistRunStatus.RUNNING_MODEL},
            ContinuationState.CANCELLED: {
                SpecialistRunStatus.RUNNING_MODEL,
                SpecialistRunStatus.WAITING_RUNTIME,
                SpecialistRunStatus.WAITING_AUTHORIZATION,
            },
        }
        updates: dict[str, Any] = {
            "last_continuation_seq": event.continuation_seq,
        }
        if event.state is ContinuationState.WAITING:
            updates["continuation_token"] = event.continuation_token
        elif event.state in {
            ContinuationState.RESUMED,
            ContinuationState.CANCELLED,
        }:
            updates["continuation_token"] = None
        return self._transition_run_unlocked(
            project_id,
            run_id,
            snapshot,
            expected=expected_by_state[event.state],
            target=target_by_state[event.state],
            updates=updates,
        )

    def _apply_attempt_head_unlocked(
        self,
        project_id: str,
        task_id: str,
        snapshot: RecordSnapshot[TaskRecord],
        event: TaskAttemptEvent,
    ) -> TaskRecord:
        current = snapshot.value
        if current.last_attempt_seq >= event.attempt_seq:
            return current
        if current.last_attempt_seq + 1 != event.attempt_seq:
            raise ExecutionStoreIntegrityError(
                "Task Attempt head is not contiguous",
            )
        updates: dict[str, Any] = {"last_attempt_seq": event.attempt_seq}
        if event.status is TaskAttemptStatus.RUNNING:
            updates.update({"progress": 0.0, "error": None})
            target = TaskStatus.RUNNING
            expected = {TaskStatus.QUEUED}
        else:
            target = TaskStatus(event.status.value)
            expected = {TaskStatus.RUNNING}
            if target is TaskStatus.SUCCEEDED:
                updates.update(
                    {
                        "progress": 1.0,
                        "result": dict(event.output or {}),
                        "output_refs": list(event.output_refs),
                        "error": None,
                    },
                )
            elif target is TaskStatus.QUARANTINED:
                updates.update(
                    {
                        "result": dict(event.output or {}),
                        "error": dict(event.error or {}),
                    },
                )
            else:
                updates["error"] = dict(event.error or {})
        return self._transition_task_unlocked(
            project_id,
            task_id,
            snapshot,
            expected=expected,
            target=target,
            updates=updates,
        )

    def _transition_run_unlocked(
        self,
        project_id: str,
        run_id: str,
        snapshot: RecordSnapshot[SpecialistRunRecord],
        *,
        expected: set[SpecialistRunStatus],
        target: SpecialistRunStatus,
        updates: Mapping[str, Any] | None = None,
        expected_checksum: str | None = None,
        updated_at: datetime | None = None,
    ) -> SpecialistRunRecord:
        current = snapshot.value
        if current.status not in expected:
            raise ExecutionStateConflict(
                "SpecialistRun status CAS conflict: expected "
                f"{sorted(item.value for item in expected)}, "
                f"got {current.status.value}",
            )
        normalized_updates = dict(updates or {})
        self._forbid_updates(
            normalized_updates,
            immutable=_RUN_IMMUTABLE_FIELDS,
            entity="SpecialistRun",
        )
        if current.status is target:
            if current.status in TERMINAL_SPECIALIST_STATUSES:
                raise ExecutionStateConflict(
                    "terminal SpecialistRun state is immutable",
                )
        elif target not in _RUN_TRANSITIONS.get(current.status, frozenset()):
            raise ExecutionStateConflict(
                f"illegal SpecialistRun transition: "
                f"{current.status.value} -> {target.value}",
            )
        dumped = current.model_dump(mode="python")
        dumped.update(normalized_updates)
        dumped.update(
            {"status": target, "updated_at": updated_at or utc_now()},
        )
        candidate = SpecialistRunRecord.model_validate(dumped)
        checksum = expected_checksum or snapshot.checksum
        return (
            self._run_store(project_id, run_id)
            .compare_and_swap(expected_checksum=checksum, value=candidate)
            .value
        )

    def _transition_task_unlocked(
        self,
        project_id: str,
        task_id: str,
        snapshot: RecordSnapshot[TaskRecord],
        *,
        expected: set[TaskStatus],
        target: TaskStatus,
        updates: Mapping[str, Any] | None = None,
        expected_checksum: str | None = None,
        updated_at: datetime | None = None,
    ) -> TaskRecord:
        current = snapshot.value
        if current.status not in expected:
            raise ExecutionStateConflict(
                "Task status CAS conflict: expected "
                f"{sorted(item.value for item in expected)}, "
                f"got {current.status.value}",
            )
        normalized_updates = dict(updates or {})
        self._forbid_updates(
            normalized_updates,
            immutable=_TASK_IMMUTABLE_FIELDS,
            entity="Task",
        )
        if current.status is target:
            if current.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                raise ExecutionStateConflict(
                    "terminal Task state is immutable",
                )
        elif target not in _TASK_TRANSITIONS.get(current.status, frozenset()):
            raise ExecutionStateConflict(
                f"illegal Task transition: {current.status.value} -> {target.value}",
            )
        dumped = current.model_dump(mode="python")
        dumped.update(normalized_updates)
        dumped.update(
            {"status": target, "updated_at": updated_at or utc_now()},
        )
        candidate = TaskRecord.model_validate(dumped)
        checksum = expected_checksum or snapshot.checksum
        result = (
            self._task_store(project_id, task_id)
            .compare_and_swap(expected_checksum=checksum, value=candidate)
            .value
        )
        logger.info(
            "task transition: project=%s task=%s kind=%s run=%s %s -> %s",
            _log_safe(project_id),
            _log_safe(task_id),
            candidate.kind.value,
            _log_safe(candidate.run_id),
            current.status.value,
            target.value,
        )
        return result

    # -- validation and paths -------------------------------------------

    @staticmethod
    def _validate_attempt_transition(
        history: Sequence[TaskAttemptEvent],
        *,
        target_status: TaskAttemptStatus,
    ) -> None:
        if not history:
            if target_status is not TaskAttemptStatus.RUNNING:
                raise ExecutionStateConflict(
                    "an Attempt stream must begin with RUNNING",
                )
            return
        current = history[-1].status
        if current in TERMINAL_TASK_ATTEMPT_STATUSES:
            raise ExecutionStateConflict("terminal Attempt cannot be reopened")
        if current is not TaskAttemptStatus.RUNNING or target_status not in (
            TERMINAL_TASK_ATTEMPT_STATUSES
        ):
            raise ExecutionStateConflict(
                f"illegal Attempt transition: {current.value} -> {target_status.value}",
            )

    @staticmethod
    def _validate_continuation_transition(
        history: Sequence[SpecialistContinuationEvent],
        *,
        target_state: ContinuationState,
    ) -> None:
        if not history:
            if target_state is not ContinuationState.WAITING:
                raise ExecutionStateConflict(
                    "a continuation stream must begin with WAITING",
                )
            return
        current = history[-1].state
        allowed = {
            ContinuationState.WAITING: {
                ContinuationState.RESUMED,
                ContinuationState.CANCELLED,
            },
            ContinuationState.RESUMED: {
                ContinuationState.COMPLETED,
                ContinuationState.CANCELLED,
            },
        }.get(current, set())
        if target_state not in allowed:
            raise ExecutionStateConflict(
                f"illegal continuation transition: "
                f"{current.value} -> {target_state.value}",
            )

    @staticmethod
    def _validate_run_for_continuation(
        run: SpecialistRunRecord,
        *,
        target_state: ContinuationState,
    ) -> None:
        expected = {
            ContinuationState.WAITING: {SpecialistRunStatus.RUNNING_MODEL},
            ContinuationState.RESUMED: {SpecialistRunStatus.WAITING_RUNTIME},
            ContinuationState.COMPLETED: {SpecialistRunStatus.RUNNING_MODEL},
            ContinuationState.CANCELLED: {
                SpecialistRunStatus.RUNNING_MODEL,
                SpecialistRunStatus.WAITING_RUNTIME,
                SpecialistRunStatus.WAITING_AUTHORIZATION,
            },
        }[target_state]
        if run.status not in expected:
            raise ExecutionStateConflict(
                "SpecialistRun state does not admit this continuation event: "
                f"expected {sorted(item.value for item in expected)}, "
                f"got {run.status.value}",
            )

    @staticmethod
    def _forbid_updates(
        updates: Mapping[str, Any],
        *,
        immutable: frozenset[str],
        entity: str,
    ) -> None:
        forbidden = (set(updates) & immutable) | (
            {"status", "updated_at"} & set(updates)
        )
        if forbidden:
            raise ExecutionPayloadConflict(
                f"{entity} update changes immutable fields: {sorted(forbidden)}",
            )

    @staticmethod
    def _run_statuses(
        value: SpecialistRunStatus
        | str
        | Collection[SpecialistRunStatus | str],
    ) -> set[SpecialistRunStatus]:
        return _coerce_statuses(value, SpecialistRunStatus)

    @staticmethod
    def _task_statuses(
        value: TaskStatus | str | Collection[TaskStatus | str],
    ) -> set[TaskStatus]:
        return _coerce_statuses(value, TaskStatus)

    @staticmethod
    def _provenance(
        owner: TraceableExecutionRecord,
        *,
        caused_by_request_id: str | None,
        caused_by_message_id: str | None,
        caused_by_message_seq: int | None,
        review_policy: ReviewPolicy | str | None,
    ) -> dict[str, Any]:
        requested_policy = (
            ReviewPolicy(review_policy) if review_policy is not None else None
        )
        overrides = {
            "caused_by_request_id": caused_by_request_id,
            "caused_by_message_id": caused_by_message_id,
            "caused_by_message_seq": caused_by_message_seq,
            "review_policy": requested_policy,
        }
        for name, value in overrides.items():
            if value is not None and value != getattr(owner, name):
                raise ExecutionStoreIntegrityError(
                    f"execution child cannot change inherited {name}",
                )
        return {
            "caused_by_request_id": owner.caused_by_request_id,
            "caused_by_message_id": owner.caused_by_message_id,
            "caused_by_message_seq": owner.caused_by_message_seq,
            "review_policy": owner.review_policy,
        }

    @staticmethod
    def _assert_provenance_inherits(
        child: TraceableExecutionRecord,
        parent: TraceableExecutionRecord,
    ) -> None:
        fields = (
            "caused_by_request_id",
            "caused_by_message_id",
            "caused_by_message_seq",
            "review_policy",
        )
        if any(
            getattr(child, name) != getattr(parent, name) for name in fields
        ):
            raise ExecutionStoreIntegrityError(
                "Task provenance must inherit its SpecialistRun",
            )

    @staticmethod
    def _equivalent(
        left: Any,
        right: Any,
        *,
        ignored: set[str] | None = None,
    ) -> bool:
        ignored_fields = {"created_at", "updated_at"} | set(ignored or ())
        left_dump = left.model_dump(mode="json")
        right_dump = right.model_dump(mode="json")
        for key in ignored_fields:
            left_dump.pop(key, None)
            right_dump.pop(key, None)
        return left_dump == right_dump

    @staticmethod
    def _assert_run_identity(
        record: SpecialistRunRecord,
        project_id: str,
        run_id: str,
    ) -> None:
        if record.project_id != project_id or record.run_id != run_id:
            raise ExecutionStoreIntegrityError(
                "SpecialistRun path and record identity disagree",
            )

    @staticmethod
    def _assert_task_identity(
        record: TaskRecord,
        project_id: str,
        task_id: str,
    ) -> None:
        if record.project_id != project_id or record.task_id != task_id:
            raise ExecutionStoreIntegrityError(
                "Task path and record identity disagree",
            )

    @staticmethod
    def _assert_authorization_identity(
        record: ExecutionAuthorizationRecord,
        project_id: str,
        authorization_id: str,
    ) -> None:
        if (
            record.project_id != project_id
            or record.authorization_id != authorization_id
        ):
            raise ExecutionStoreIntegrityError(
                "authorization path and record identity disagree",
            )

    @staticmethod
    def _assert_quarantine_identity(
        record: QuarantinedTaskResult,
        project_id: str,
        task_id: str,
    ) -> None:
        if record.project_id != project_id or record.task_id != task_id:
            raise ExecutionStoreIntegrityError(
                "quarantine path and record identity disagree",
            )

    @staticmethod
    def _authorization_request_signature(
        record: ExecutionAuthorizationRecord,
    ) -> dict[str, Any]:
        dumped = record.model_dump(mode="json")
        for field in {
            "authorization_id",
            "authorization_token",
            "status",
            "decision",
            "metadata",
            "created_at",
            "updated_at",
            "decided_at",
        }:
            dumped.pop(field, None)
        return dumped

    @staticmethod
    def _assert_stream_ownership(
        records: Sequence[Any],
        *,
        project_id: str,
        run_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        for record in records:
            if record.project_id != project_id:
                raise ExecutionStoreIntegrityError(
                    "stream record belongs to another Project",
                )
            if run_id is not None and record.run_id != run_id:
                raise ExecutionStoreIntegrityError(
                    "stream record belongs to another SpecialistRun",
                )
            if task_id is not None and record.task_id != task_id:
                raise ExecutionStoreIntegrityError(
                    "stream record belongs to another Task",
                )

    @staticmethod
    def _safe(value: str, label: str) -> str:
        return require_safe_runtime_segment(value, label=label)

    def _validate_optional_ids(self, **values: str | None) -> None:
        for label, value in values.items():
            if value is not None:
                self._safe(value, label)

    def _safe_project_child(
        self,
        project_id: str,
        child_id: str,
        *,
        child_label: str,
    ) -> tuple[str, str]:
        project_id = self._safe(project_id, "project_id")
        child_id = self._safe(child_id, child_label)
        self._require_project(project_id)
        return project_id, child_id

    def _require_project(self, project_id: str) -> Path:
        project_root = self.data_root / project_id
        try:
            root_stat = project_root.lstat()
            project_stat = (project_root / "project.json").lstat()
        except FileNotFoundError as exc:
            raise ExecutionStoreError(
                f"Project does not exist: {project_id}",
            ) from exc
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(
            root_stat.st_mode,
        ):
            raise UnsafeExecutionPath(
                "Project root must be a regular, non-symlink directory",
            )
        if stat.S_ISLNK(project_stat.st_mode) or not stat.S_ISREG(
            project_stat.st_mode,
        ):
            raise UnsafeExecutionPath(
                "project.json must be a regular, non-symlink file",
            )
        return project_root

    def _runtime_root(self, project_id: str) -> Path:
        return self.data_root / project_id / "runtime"

    @contextmanager
    def _project_lock(
        self,
        project_id: str,
        *,
        _lifecycle_lock_held: bool = False,
    ):
        # Match ProjectStore's lifecycle lock before touching Runtime paths so
        # a concurrent delete cannot be followed by a late writer recreating a
        # phantom Project directory.
        if _lifecycle_lock_held:
            self._require_project(project_id)
            with CrossProcessFileLock(
                self._runtime_root(project_id)
                / "locks"
                / "execution-runtime.lock",
                timeout_seconds=self.lock_timeout_seconds,
            ):
                yield
            return
        with CrossProcessFileLock(
            self.data_root / ".locks" / f"project-{project_id}.lock",
            timeout_seconds=self.lock_timeout_seconds,
            shared=True,
        ):
            self._require_project(project_id)
            with CrossProcessFileLock(
                self._runtime_root(project_id)
                / "locks"
                / "execution-runtime.lock",
                timeout_seconds=self.lock_timeout_seconds,
            ):
                yield

    @contextmanager
    def _project_lock_read(self, project_id: str):
        """Shared-lock variant of :meth:`_project_lock` for read-only paths.

        Both locks are taken as ``LOCK_SH`` so concurrent readers never block
        each other; they only wait for a writer.  Callers must not mutate any
        file under this lock.
        """
        project_id = self._safe(project_id, "project_id")
        with CrossProcessFileLock(
            self.data_root / ".locks" / f"project-{project_id}.lock",
            timeout_seconds=self.lock_timeout_seconds,
            shared=True,
        ):
            self._require_project(project_id)
            with CrossProcessFileLock(
                self._runtime_root(project_id)
                / "locks"
                / "execution-runtime.lock",
                timeout_seconds=self.lock_timeout_seconds,
                shared=True,
            ):
                yield

    def _run_store(
        self,
        project_id: str,
        run_id: str,
    ) -> AtomicJsonRecordStore[SpecialistRunRecord]:
        return AtomicJsonRecordStore(
            self._runtime_root(project_id) / "runs" / run_id / "run.json",
            SpecialistRunRecord,
        )

    def _messages_store(
        self,
        project_id: str,
        run_id: str,
    ) -> DurableJsonlStore[SpecialistMessageRecord]:
        return DurableJsonlStore(
            self._runtime_root(project_id)
            / "runs"
            / run_id
            / "messages.jsonl",
            SpecialistMessageRecord,
        )

    def _continuations_store(
        self,
        project_id: str,
        run_id: str,
    ) -> DurableJsonlStore[SpecialistContinuationEvent]:
        return DurableJsonlStore(
            self._runtime_root(project_id)
            / "runs"
            / run_id
            / "continuations.jsonl",
            SpecialistContinuationEvent,
        )

    def _task_store(
        self,
        project_id: str,
        task_id: str,
    ) -> AtomicJsonRecordStore[TaskRecord]:
        return AtomicJsonRecordStore(
            self._runtime_root(project_id) / "tasks" / task_id / "task.json",
            TaskRecord,
        )

    def _attempts_store(
        self,
        project_id: str,
        task_id: str,
    ) -> DurableJsonlStore[TaskAttemptEvent]:
        return DurableJsonlStore(
            self._runtime_root(project_id)
            / "tasks"
            / task_id
            / "attempts.jsonl",
            TaskAttemptEvent,
        )

    def _authorization_store(
        self,
        project_id: str,
        authorization_id: str,
    ) -> AtomicJsonRecordStore[ExecutionAuthorizationRecord]:
        return AtomicJsonRecordStore(
            self._runtime_root(project_id)
            / "authorizations"
            / f"{authorization_id}.json",
            ExecutionAuthorizationRecord,
        )

    def _authorization_records(
        self,
        project_id: str,
    ) -> list[ExecutionAuthorizationRecord]:
        root = self._runtime_root(project_id) / "authorizations"
        if not root.exists():
            return []
        records: list[ExecutionAuthorizationRecord] = []
        for path in sorted(root.glob("*.json")):
            record = AtomicJsonRecordStore(
                path,
                ExecutionAuthorizationRecord,
            ).read()
            self._assert_authorization_identity(
                record,
                project_id,
                self._safe(path.stem, "authorization_id"),
            )
            records.append(record)
        return records

    def _quarantine_store(
        self,
        project_id: str,
        task_id: str,
    ) -> AtomicJsonRecordStore[QuarantinedTaskResult]:
        return AtomicJsonRecordStore(
            self._runtime_root(project_id) / "quarantine" / f"{task_id}.json",
            QuarantinedTaskResult,
        )


ExecutionStore = ProjectExecutionStore


def _coerce_statuses(value: Any, enum_type: type[E]) -> set[E]:
    if isinstance(value, (str, enum_type)):
        return {enum_type(value)}
    statuses = {enum_type(item) for item in value}
    if not statuses:
        raise ValueError("expected_status cannot be empty")
    return statuses


__all__ = [
    "AuthorizationTokenConflict",
    "ExecutionPayloadConflict",
    "ExecutionStateConflict",
    "ExecutionStore",
    "ExecutionStoreError",
    "ExecutionStoreIntegrityError",
    "ProjectExecutionStore",
    "QuarantineWriteResult",
    "UnsafeExecutionPath",
]
