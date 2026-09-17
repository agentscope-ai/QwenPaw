# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Pydantic records persisted below one Project's ``runtime/`` directory."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from domain.enums import (
    CreatorGoalStatus,
    CreatorSessionStatus,
    TransactionStatus,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Runtime timestamps must include a timezone")
    return value.astimezone(UTC)


AwareDatetime = Annotated[datetime, AfterValidator(_aware_utc)]
NonEmptyString = Annotated[str, Field(min_length=1)]
Generation = Annotated[int, Field(ge=0)]


class StrictRuntimeModel(BaseModel):
    # Stores frequently receive an existing model from a transition function.
    # Revalidate instances so ``model_copy(update=...)`` cannot bypass enum,
    # timestamp or cross-field invariants before persistence.
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        revalidate_instances="always",
    )


class SyncStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    INVALID = "invalid"


class ChangeOrigin(StrEnum):
    INITIAL_CREATION = "initial_creation"
    AGENTDOCK_INTERRUPT = "agentdock_interrupt"
    AGENTDOCK_IDLE_GOAL = "agentdock_idle_goal"
    FRONTEND_EDIT = "frontend_edit"
    RUNTIME_TASK = "runtime_task"


class ReviewPolicy(StrEnum):
    AUTO_FIX = "auto_fix"
    REQUIRE_REVIEW = "require_review"


# Origins whose commits are allowed to gate their changes behind a review.
# AgentDock interrupts and idle goals capture a user-intent boundary; runtime
# tasks cover autonomously generated media (images/videos) that must always be
# reviewed before they are treated as accepted.
_REVIEW_REQUIRING_ORIGINS = frozenset(
    {
        ChangeOrigin.AGENTDOCK_INTERRUPT,
        ChangeOrigin.AGENTDOCK_IDLE_GOAL,
        ChangeOrigin.RUNTIME_TASK,
    },
)


class ProjectChangeKind(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    MOVE = "move"
    REORDER = "reorder"
    SELECT_ASSET = "select_asset"


class ReviewStatus(StrEnum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    SUPERSEDED = "SUPERSEDED"


class ReviewOperationDecision(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REVISED = "REVISED"
    SUPERSEDED_BY_USER_EDIT = "SUPERSEDED_BY_USER_EDIT"


class IdempotencyStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MessageChannel(StrEnum):
    AGENTDOCK = "agentdock"
    COMPOSER = "composer"
    FRONTEND = "frontend"
    RUNTIME = "runtime"


class MessageClassification(StrEnum):
    READ_ONLY_QUESTION = "read_only_question"
    MUTATION_INSTRUCTION = "mutation_instruction"
    REVIEW_COMMENT = "review_comment"
    REVIEW_REVISE = "review_revise"
    WORKSPACE_COMMAND = "workspace_command"


class QueuedMessageState(StrEnum):
    QUEUED = "QUEUED"
    APPENDED = "APPENDED"
    CANCELLED = "CANCELLED"


class OutboxState(StrEnum):
    PENDING = "PENDING"
    APPENDED = "APPENDED"
    CANCELLED = "CANCELLED"


class MessageContentPart(StrictRuntimeModel):
    type: Literal["text", "image_url", "video_url", "audio", "document"]
    text: str | None = None
    image_url: dict[str, Any] | None = None
    video_url: dict[str, Any] | None = None
    attachment: dict[str, Any] | None = None


class CreatorSessionRecord(StrictRuntimeModel):
    session_id: NonEmptyString
    project_id: NonEmptyString
    schema_prompt_hash: str | None = None
    status: CreatorSessionStatus = CreatorSessionStatus.IDLE
    active_goal_id: str | None = None
    active_run_id: str | None = None
    active_round_id: str | None = None
    provider_conversation_handle: str | None = None
    in_flight_assistant_message_id: str | None = None
    open_action_ids: list[str] = Field(default_factory=list)
    queued_user_message_count: int = Field(default=0, ge=0)
    last_message_seq: int = Field(default=0, ge=0)
    last_event_seq: int = Field(default=0, ge=0)
    last_consumed_message_seq: int = Field(default=0, ge=0)
    error: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_sequence_heads(self) -> CreatorSessionRecord:
        if self.last_consumed_message_seq > self.last_message_seq:
            raise ValueError(
                "last consumed message seq cannot exceed the message head",
            )
        if len(self.open_action_ids) != len(set(self.open_action_ids)):
            raise ValueError("open action IDs cannot contain duplicates")
        return self


class CreatorConversationRecord(StrictRuntimeModel):
    conversation_id: NonEmptyString
    project_id: NonEmptyString
    creator_session_id: NonEmptyString
    title: NonEmptyString = "Default"
    is_default: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime = Field(default_factory=utc_now)


class CreatorGoalRecord(StrictRuntimeModel):
    goal_id: NonEmptyString
    project_id: NonEmptyString
    creator_session_id: NonEmptyString
    conversation_id: NonEmptyString
    root_message_seq: int = Field(ge=1)
    intent: NonEmptyString
    success_criteria: list[Any] = Field(default_factory=list)
    status: CreatorGoalStatus = CreatorGoalStatus.ACTIVE
    completion_intent: str | None = None
    completion_outcome: dict[str, Any] | None = None
    current_round_id: str | None = None
    remaining_work_refs: list[str] = Field(default_factory=list)
    last_consumed_message_seq: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)


class CreatorMessageRecord(StrictRuntimeModel):
    message_id: NonEmptyString
    project_id: NonEmptyString
    creator_session_id: NonEmptyString
    conversation_id: NonEmptyString
    message_seq: int = Field(ge=1)
    role: Literal["system", "user", "assistant", "tool"]
    content_parts: list[MessageContentPart] = Field(min_length=1)
    client_message_id: str | None = None
    request_hash: str | None = None
    source: NonEmptyString = "runtime"
    channel: MessageChannel = MessageChannel.RUNTIME
    classification: MessageClassification | None = None
    review_boundary: ReviewBoundary | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    completed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_idempotency_hash(self) -> CreatorMessageRecord:
        if bool(self.client_message_id) != bool(self.request_hash):
            raise ValueError(
                "client_message_id and request_hash must be present together",
            )
        return self


class SessionEventRecord(StrictRuntimeModel):
    event_id: NonEmptyString
    project_id: NonEmptyString
    creator_session_id: NonEmptyString
    event_seq: int = Field(ge=1)
    event_type: NonEmptyString
    actor: NonEmptyString = "runtime"
    round_id: str | None = None
    message_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime = Field(default_factory=utc_now)


class QueuedMessageRecord(StrictRuntimeModel):
    queued_message_id: NonEmptyString
    queue_seq: int = Field(ge=1)
    project_id: NonEmptyString
    creator_session_id: NonEmptyString
    conversation_id: NonEmptyString
    client_message_id: NonEmptyString
    request_hash: NonEmptyString
    content_parts: list[MessageContentPart] = Field(min_length=1)
    source: NonEmptyString = "user"
    state: QueuedMessageState = QueuedMessageState.QUEUED
    appended_message_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)


class OutboxRecord(StrictRuntimeModel):
    record_id: NonEmptyString
    outbox_seq: int = Field(ge=1)
    project_id: NonEmptyString
    creator_session_id: NonEmptyString
    conversation_id: NonEmptyString
    outbox_id: NonEmptyString
    request_hash: NonEmptyString
    content_parts: list[MessageContentPart] = Field(min_length=1)
    source: NonEmptyString = "frontend_manual_edit"
    state: OutboxState = OutboxState.PENDING
    linked_message_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)


class RuntimeProjectState(StrictRuntimeModel):
    project_id: NonEmptyString
    active_session_id: str | None = None
    active_goal_id: str | None = None
    active_round_id: str | None = None
    last_project_generation: Generation
    last_project_etag: NonEmptyString
    accepted_generation: Generation
    accepted_etag: NonEmptyString
    sync_status: SyncStatus = SyncStatus.HEALTHY
    updated_at: AwareDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_accepted_baseline(self) -> RuntimeProjectState:
        if self.accepted_generation > self.last_project_generation:
            raise ValueError(
                "accepted generation cannot exceed the current Project generation",
            )
        if (
            self.accepted_generation == self.last_project_generation
            and self.accepted_etag != self.last_project_etag
        ):
            raise ValueError(
                "equal accepted/current generations must have the same ETag",
            )
        return self


class ReviewBoundary(StrictRuntimeModel):
    # AgentDock interrupts carry a user request message; media/runtime reviews
    # (e.g. an autonomously generated image or video) have no originating
    # message, so the request provenance and interrupted run are optional.
    request_message_seq: int | None = Field(default=None, ge=1)
    request_id: NonEmptyString | None = None
    interrupted_run_id: NonEmptyString | None = None
    accepted_generation: Generation
    accepted_etag: NonEmptyString
    captured_at: AwareDatetime = Field(default_factory=utc_now)


class ChangeRoundRecord(StrictRuntimeModel):
    round_id: NonEmptyString
    project_id: NonEmptyString
    origin: ChangeOrigin
    review_policy: ReviewPolicy
    review_boundary: ReviewBoundary | None = None
    status: TransactionStatus = TransactionStatus.ACTIVE
    caused_by_request_id: str | None = None
    caused_by_message_seq: int | None = Field(default=None, ge=1)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_review_boundary(self) -> ChangeRoundRecord:
        if self.review_policy is ReviewPolicy.REQUIRE_REVIEW:
            if self.origin not in _REVIEW_REQUIRING_ORIGINS:
                raise ValueError(
                    "only an AgentDock interrupt/idle goal or a runtime task "
                    "may require review",
                )
            if self.review_boundary is None:
                raise ValueError(
                    "a review-required round must capture a ReviewBoundary",
                )
            if self.caused_by_request_id not in {
                None,
                self.review_boundary.request_id,
            }:
                raise ValueError(
                    "round request provenance does not match ReviewBoundary",
                )
            if self.caused_by_message_seq not in {
                None,
                self.review_boundary.request_message_seq,
            }:
                raise ValueError(
                    "round message provenance does not match ReviewBoundary",
                )
        elif self.review_boundary is not None:
            raise ValueError("an auto-fix round cannot carry a ReviewBoundary")
        return self


class ProjectChange(StrictRuntimeModel):
    kind: ProjectChangeKind
    json_pointer: str | None = None
    file_id: str | None = None
    target_ref: str | None = None
    before_hash: NonEmptyString
    after_hash: NonEmptyString
    before: Any | None = None
    after: Any | None = None

    @model_validator(mode="after")
    def validate_locator(self) -> ProjectChange:
        if (
            self.json_pointer is None
            and self.file_id is None
            and self.target_ref is None
        ):
            raise ValueError(
                "a Project change needs a JSON pointer, file ID or target ref",
            )
        if self.json_pointer is not None and not self.json_pointer.startswith(
            "/",
        ):
            raise ValueError(
                "json_pointer must be an RFC 6901 pointer beginning with '/'",
            )
        return self


class RuntimeChangeSet(StrictRuntimeModel):
    round_id: NonEmptyString
    project_id: NonEmptyString
    origin: ChangeOrigin
    review_policy: ReviewPolicy
    caused_by_request_id: str | None = None
    caused_by_message_seq: int | None = Field(default=None, ge=1)
    base_generation: Generation
    final_generation: Generation
    base_etag: NonEmptyString
    final_etag: NonEmptyString
    changes: list[ProjectChange]
    created_at: AwareDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_generation_order(self) -> RuntimeChangeSet:
        if self.final_generation < self.base_generation:
            raise ValueError(
                "ChangeSet final generation cannot precede its base",
            )
        return self


class ReviewOperation(ProjectChange):
    operation_id: NonEmptyString
    ui_locator: dict[str, str] = Field(default_factory=dict)
    decision: ReviewOperationDecision = ReviewOperationDecision.PENDING


class ReviewRecord(StrictRuntimeModel):
    review_id: NonEmptyString
    round_id: NonEmptyString
    # Optional for media/runtime reviews that have no originating AgentDock
    # message (see ReviewBoundary).
    request_id: NonEmptyString | None = None
    request_message_seq: int | None = Field(default=None, ge=1)
    interrupted_run_id: NonEmptyString | None = None
    baseline_generation: Generation
    baseline_etag: NonEmptyString
    candidate_generation: Generation
    candidate_etag: NonEmptyString
    decision_token: NonEmptyString
    status: ReviewStatus = ReviewStatus.PENDING
    operations: list[ReviewOperation] = Field(min_length=1)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_review_state(self) -> ReviewRecord:
        if self.candidate_generation < self.baseline_generation:
            raise ValueError("review candidate cannot precede its baseline")
        operation_ids = [
            operation.operation_id for operation in self.operations
        ]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("Review operation IDs must be unique")
        pending = any(
            operation.decision is ReviewOperationDecision.PENDING
            for operation in self.operations
        )
        if self.status is ReviewStatus.PENDING and not pending:
            raise ValueError(
                "a pending Review must contain a pending operation",
            )
        if self.status is ReviewStatus.RESOLVED and pending:
            raise ValueError(
                "a resolved Review cannot contain pending operations",
            )
        return self


# Design prose and API responses use "snapshot" for the same persisted Review.
ReviewSnapshot = ReviewRecord


class FieldBlockRecord(StrictRuntimeModel):
    block_id: NonEmptyString
    project_id: NonEmptyString
    json_pointer: str
    owner_kind: Literal["user", "agent", "runtime"]
    owner_id: NonEmptyString
    token: NonEmptyString
    base_field_hash: NonEmptyString
    acquired_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_expiry(self) -> FieldBlockRecord:
        if self.expires_at <= self.acquired_at:
            raise ValueError("field block expiry must follow acquisition")
        return self


class IdempotencyRecord(StrictRuntimeModel):
    record_id: NonEmptyString
    owner_id: NonEmptyString
    scope: NonEmptyString
    key_hash: NonEmptyString
    request_hash: NonEmptyString
    status: IdempotencyStatus = IdempotencyStatus.IN_PROGRESS
    response_status: int | None = Field(default=None, ge=100, le=599)
    response: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_result(self) -> IdempotencyRecord:
        if self.status is IdempotencyStatus.IN_PROGRESS:
            if self.response is not None or self.error is not None:
                raise ValueError(
                    "in-progress idempotency records cannot contain a result",
                )
        elif self.status is IdempotencyStatus.COMPLETED:
            if self.response is None or self.error is not None:
                raise ValueError(
                    "completed idempotency records require only a response",
                )
        elif self.status is IdempotencyStatus.FAILED:
            if self.error is None or self.response is not None:
                raise ValueError(
                    "failed idempotency records require only an error",
                )
        return self
