# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Typed records for file-native SpecialistRun and Task execution state."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from domain.enums import (
    SpecialistRole,
    SpecialistRunStatus,
    TaskKind,
    TaskStatus,
)

from .models import (
    AwareDatetime,
    NonEmptyString,
    ReviewPolicy,
    StrictRuntimeModel,
    utc_now,
)


class TraceableExecutionRecord(StrictRuntimeModel):
    """Causal ownership frozen when a Run or Task is admitted.

    Runtime work keeps this provenance even when a provider result arrives in
    a later wall-clock round.  In particular, ``review_policy`` must never be
    inferred from an mtime or from whichever Session happens to be active when
    the result is consumed.
    """

    caused_by_request_id: str | None = None
    caused_by_message_id: str | None = None
    caused_by_message_seq: int | None = Field(default=None, ge=1)
    review_policy: ReviewPolicy = ReviewPolicy.AUTO_FIX

    @model_validator(mode="after")
    def validate_review_provenance(self) -> TraceableExecutionRecord:
        if self.review_policy is ReviewPolicy.REQUIRE_REVIEW and (
            self.caused_by_request_id is None
            or self.caused_by_message_seq is None
        ):
            raise ValueError(
                "require_review records need caused_by_request_id and "
                "caused_by_message_seq",
            )
        return self


class SpecialistRunRecord(TraceableExecutionRecord):
    run_id: NonEmptyString
    project_id: NonEmptyString
    round_id: NonEmptyString
    role: SpecialistRole
    status: SpecialistRunStatus = SpecialistRunStatus.QUEUED
    target_refs: list[str] = Field(default_factory=list)
    input_generation: int = Field(ge=0)
    input_etag: NonEmptyString
    related_run_id: str | None = None
    supersedes_run_id: str | None = None
    prompt_spec_id: str | None = None
    prompt_hash: str | None = None
    request_fingerprint: str | None = None
    read_set: list[dict[str, Any]] = Field(default_factory=list)
    continuation_token: str | None = None
    provider_conversation_handle: str | None = None
    final_marker: str | None = None
    final_summary_text: str | None = None
    last_continuation_seq: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_timestamps(self) -> SpecialistRunRecord:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        return self


class TaskRecord(TraceableExecutionRecord):
    task_id: NonEmptyString
    project_id: NonEmptyString
    round_id: str | None = None
    run_id: str | None = None
    kind: TaskKind
    status: TaskStatus = TaskStatus.QUEUED
    request_fingerprint: NonEmptyString
    idempotency_key: str | None = None
    input_generation: int | None = Field(default=None, ge=0)
    input_etag: str | None = None
    expected_target_version: str | None = None
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    read_set: list[dict[str, Any]] = Field(default_factory=list)
    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    last_attempt_seq: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_task_shape(self) -> TaskRecord:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if (self.input_generation is None) != (self.input_etag is None):
            raise ValueError(
                "input_generation and input_etag must be present together",
            )
        return self


class SpecialistMessageRecord(TraceableExecutionRecord):
    message_id: NonEmptyString
    project_id: NonEmptyString
    run_id: NonEmptyString
    message_seq: int = Field(ge=1)
    role: Literal["system", "user", "assistant", "tool"]
    content_parts: list[Any] = Field(min_length=1)
    provider_message_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime = Field(default_factory=utc_now)


class TaskAttemptStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    QUARANTINED = "QUARANTINED"


TERMINAL_TASK_ATTEMPT_STATUSES = frozenset(
    {
        TaskAttemptStatus.SUCCEEDED,
        TaskAttemptStatus.FAILED,
        TaskAttemptStatus.CANCELLED,
        TaskAttemptStatus.QUARANTINED,
    },
)


class TaskAttemptEvent(TraceableExecutionRecord):
    event_id: NonEmptyString
    project_id: NonEmptyString
    task_id: NonEmptyString
    attempt_id: NonEmptyString
    attempt_number: int = Field(ge=1)
    attempt_seq: int = Field(ge=1)
    status: TaskAttemptStatus
    provider_task_id: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    output_refs: list[str] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    created_at: AwareDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_attempt_completion(self) -> TaskAttemptEvent:
        terminal = self.status in TERMINAL_TASK_ATTEMPT_STATUSES
        if terminal != (self.finished_at is not None):
            raise ValueError(
                "terminal attempt events require finished_at and RUNNING does not",
            )
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("finished_at cannot precede started_at")
        return self


class ContinuationState(StrEnum):
    WAITING = "WAITING"
    RESUMED = "RESUMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SpecialistContinuationEvent(TraceableExecutionRecord):
    event_id: NonEmptyString
    continuation_id: NonEmptyString
    project_id: NonEmptyString
    run_id: NonEmptyString
    task_id: str | None = None
    continuation_seq: int = Field(ge=1)
    continuation_token: NonEmptyString
    state: ContinuationState
    request: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    created_at: AwareDatetime = Field(default_factory=utc_now)
    completed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_completion_timestamp(self) -> SpecialistContinuationEvent:
        terminal = self.state in {
            ContinuationState.COMPLETED,
            ContinuationState.CANCELLED,
        }
        if terminal != (self.completed_at is not None):
            raise ValueError(
                "terminal continuation events require completed_at",
            )
        if (
            self.completed_at is not None
            and self.completed_at < self.created_at
        ):
            raise ValueError("completed_at cannot precede created_at")
        return self


class ExecutionAuthorizationStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ExecutionAuthorizationRecord(TraceableExecutionRecord):
    authorization_id: NonEmptyString
    project_id: NonEmptyString
    round_id: NonEmptyString
    run_id: NonEmptyString
    task_id: str | None = None
    execution_request_id: NonEmptyString
    operation: NonEmptyString
    target_scope: list[NonEmptyString] = Field(min_length=1)
    authorization_token: NonEmptyString
    status: ExecutionAuthorizationStatus = ExecutionAuthorizationStatus.PENDING
    summary: NonEmptyString
    scope: dict[str, Any] | None = None
    requested_provider: str | None = None
    requested_model: str | None = None
    # Deprecated: local price estimation was removed (stale price tables
    # mislead). Field kept so durable records written before the removal
    # still validate under extra=forbid; never written or surfaced.
    estimated_cost: float | None = Field(default=None, ge=0)
    requested_candidates: int | None = Field(default=None, ge=1)
    decision: dict[str, Any] | None = None
    expires_at: AwareDatetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)
    decided_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_authorization_state(self) -> ExecutionAuthorizationRecord:
        terminal = self.status is not ExecutionAuthorizationStatus.PENDING
        if terminal != (self.decided_at is not None):
            raise ValueError(
                "terminal authorizations require decided_at and PENDING does not",
            )
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.decided_at is not None and self.decided_at < self.created_at:
            raise ValueError("decided_at cannot precede created_at")
        if len(self.target_scope) != len(set(self.target_scope)):
            raise ValueError("target_scope cannot contain duplicates")
        return self


class QuarantinedTaskResult(TraceableExecutionRecord):
    quarantine_id: NonEmptyString
    project_id: NonEmptyString
    round_id: str | None = None
    task_id: NonEmptyString
    run_id: str | None = None
    reason: NonEmptyString
    request_fingerprint: NonEmptyString
    input_generation: int | None = Field(default=None, ge=0)
    input_etag: str | None = None
    result: dict[str, Any]
    input_refs: list[str] = Field(default_factory=list)
    created_at: AwareDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_input_snapshot(self) -> QuarantinedTaskResult:
        if (self.input_generation is None) != (self.input_etag is None):
            raise ValueError(
                "input_generation and input_etag must be present together",
            )
        return self


__all__ = [
    "ContinuationState",
    "ExecutionAuthorizationRecord",
    "ExecutionAuthorizationStatus",
    "QuarantinedTaskResult",
    "SpecialistContinuationEvent",
    "SpecialistMessageRecord",
    "SpecialistRunRecord",
    "TERMINAL_TASK_ATTEMPT_STATUSES",
    "TaskAttemptEvent",
    "TaskAttemptStatus",
    "TaskRecord",
    "TraceableExecutionRecord",
]
