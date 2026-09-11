# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Narrow ports shared by persistent media workers.

Workers deliberately receive these ports.  They never treat an in-process
queue, coroutine, or provider object as authoritative state; the injected Task
Registry and validity resolver are backed by durable Creator Runtime files.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ExecutionValidity:
    """Current scoped-CAS facts used when importing one finished result."""

    target_version: str | None
    read_versions: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class ExecutionValidityResolver(Protocol):
    async def resolve(self, task: Mapping[str, Any]) -> ExecutionValidity:
        ...


@runtime_checkable
class TaskRegistryPort(Protocol):
    async def register(
        self,
        *,
        project_id: str,
        kind: Any,
        target_ref: str,
        input_fingerprint: str,
        idempotency_key: str,
        transaction_id: str | None = None,
        specialist_run_id: str | None = None,
        expected_target_version: str | None = None,
        read_set: Sequence[Mapping[str, Any]] = (),
        task_id: str | None = None,
    ) -> dict[str, Any]:
        ...

    async def get(self, task_id: str) -> dict[str, Any] | None:
        ...

    async def start_attempt(
        self,
        task_id: str,
        *,
        provider_task_id: str | None = None,
        input_payload: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        ...

    async def set_progress(
        self,
        task_id: str,
        progress: float,
    ) -> dict[str, Any]:
        ...

    async def complete(
        self,
        task_id: str,
        *,
        result: Mapping[str, Any],
        result_refs: Sequence[str] = (),
        result_input_fingerprint: str,
        current_target_version: str | None,
        current_read_versions: Mapping[str, Any],
    ) -> Any:
        ...

    async def mark_imported(self, task_id: str) -> dict[str, Any]:
        ...

    async def fail(
        self,
        task_id: str,
        *,
        error: Mapping[str, Any],
    ) -> dict[str, Any]:
        ...

    async def retry_failed(
        self,
        task_id: str,
        *,
        retryable_error_kinds: Sequence[str],
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        ...

    async def recovery_candidates(self) -> Sequence[Any]:
        ...


@runtime_checkable
class AssetIngestSuccessObserverPort(Protocol):
    """Durably schedule any semantic action recorded by a successful ingest.

    The observer is a Runtime concern.  The ingest worker only hands it the
    committed Task record and never writes Text Workspace state itself.
    """

    async def observe_success(self, task: Mapping[str, Any]) -> Any:
        ...


@dataclass(frozen=True, slots=True)
class MediaOutput:
    """A provider result after bytes/checksum/specification materialization."""

    url: str
    checksum: str
    media_type: str
    size_bytes: int | None = None
    duration_seconds: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class MediaOutputMaterializer(Protocol):
    async def materialize(
        self,
        output: Mapping[str, Any],
        *,
        expected_media_kind: str,
    ) -> MediaOutput:
        ...


@dataclass(frozen=True, slots=True)
class ArtifactImport:
    project_id: str
    slot_id: str
    slot_kind: str
    target_ref: str
    created_by: str
    transaction_id: str
    based_on_revision_id: str | None
    input_fingerprint: str
    model_run_id: str | None = None
    provenance_refs: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


def task_was_quarantined(completion: Any) -> bool:
    """Support the runtime TaskCompletion and intentionally small test fakes."""

    if hasattr(completion, "quarantined"):
        return bool(completion.quarantined)
    if isinstance(completion, Mapping):
        return bool(completion.get("quarantined"))
    return False


def task_from_completion(completion: Any) -> Mapping[str, Any]:
    if hasattr(completion, "task"):
        return completion.task
    if isinstance(completion, Mapping):
        nested = completion.get("task")
        return nested if isinstance(nested, Mapping) else completion
    raise TypeError("Task completion does not expose a task record")
