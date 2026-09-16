# -*- coding: utf-8 -*-
"""Versioned Host task contracts, independent of any chat/runtime adapter."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

Identity = Annotated[str, Field(min_length=1, max_length=256)]
Engagement = Literal["delegated", "direct"]
TaskStatus = Literal[
    "pending",
    "running",
    "waiting_for_input",
    "waiting_for_setup",
    "waiting_for_approval",
    "paused",
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
]
TERMINAL_STATUSES = frozenset(
    {"succeeded", "failed", "cancelled", "interrupted"},
)
WAITING_STATUSES = frozenset(
    {"waiting_for_input", "waiting_for_setup", "waiting_for_approval"},
)
RecoveryState = Literal["none", "reconciling", "unresolved"]
CommandState = Literal[
    "prepared",
    "in_flight",
    "accepted",
    "rejected",
    "unknown",
]


def canonical_json(value: Any) -> str:
    """Serialize finite JSON for durable request/event comparisons."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ActionDescriptor(Contract):
    """Registered server-owned action; callers never supply an adapter ref."""

    schema_version: Literal[1] = 1
    app_id: Identity
    action_id: Identity
    summary: Annotated[str, Field(min_length=1)]
    engagements: tuple[Engagement, ...] = Field(min_length=1)
    input_schema: dict[str, Any]
    output_types: tuple[Identity, ...] = ()
    permissions: tuple[Identity, ...] = ()
    effects: tuple[Identity, ...] = ()
    adapter_ref: Identity

    @model_validator(mode="after")
    def validate_schema(self) -> ActionDescriptor:
        if len(set(self.engagements)) != len(self.engagements):
            raise ValueError("engagements must be unique")

        # Schemas must be self-contained. Validation must never retrieve a
        # remote document or resolve an App-supplied filesystem reference.
        def check_refs(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"$ref", "$dynamicRef"} and (
                        not isinstance(item, str) or not item.startswith("#")
                    ):
                        raise ValueError("action schemas require local refs")
                    check_refs(item)
            elif isinstance(value, list):
                for item in value:
                    check_refs(item)

        canonical_json(self.input_schema)
        check_refs(self.input_schema)
        dialect = self.input_schema.get("$schema")
        if dialect not in (None, Draft202012Validator.META_SCHEMA["$id"]):
            raise ValueError("action schemas use JSON Schema 2020-12")
        if self.input_schema.get("type") != "object":
            raise ValueError("action input schema must describe an object")
        Draft202012Validator.check_schema(self.input_schema)
        return self

    @property
    def descriptor_digest(self) -> str:
        return content_digest(self.model_dump(mode="json"))

    def validate_inputs(self, inputs: dict[str, Any]) -> None:
        canonical_json(inputs)
        errors = Draft202012Validator(self.input_schema).iter_errors(inputs)
        error = next(errors, None)
        if error is not None:
            # Do not echo possibly sensitive inputs in error messages.
            raise ValueError(f"invalid action input at {error.json_path}")


class TaskScope(Contract):
    """Identity resolved by the Host, never trusted from an HTTP payload."""

    principal_id: Identity
    workspace_id: Identity
    app_id: Identity


class TaskOrigin(Contract):
    engagement: Engagement
    origin_ref: Identity
    app_session_ref: Identity | None = None
    return_session_ref: Identity | None = None

    @model_validator(mode="after")
    def validate_origin(self) -> TaskOrigin:
        if self.engagement == "delegated" and not self.return_session_ref:
            raise ValueError("delegated tasks require a return session")
        if self.engagement == "direct":
            if not self.app_session_ref or self.return_session_ref:
                raise ValueError("direct tasks require only an App session")
        return self


class ExecutorRunRef(Contract):
    executor_id: Identity
    session_id: Identity
    run_id: Identity


class ArtifactProducer(Contract):
    """Stable provenance for one App-published artifact version."""

    app_id: Identity
    action_id: Identity
    task_id: Identity
    executor_id: Identity
    session_id: Identity
    run_id: Identity
    source_id: Identity


class ArtifactRef(Contract):
    """Reference to an immutable version in the Host artifact store."""

    schema_version: Literal[1] = 1
    artifact_id: Identity
    type: Identity
    version: int = Field(ge=1)
    name: Annotated[str, Field(min_length=1, max_length=512)]
    media_type: Annotated[str, Field(min_length=1, max_length=256)]
    size_bytes: int = Field(ge=0)
    digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    producer: ArtifactProducer
    created_at: float


class ProjectRef(Contract):
    """Reference to an App-owned mutable project at a known revision."""

    schema_version: Literal[1] = 1
    app_id: Identity
    project_id: Identity
    kind: Identity
    revision: int = Field(ge=1)


class TaskInputOption(Contract):
    label: Annotated[str, Field(min_length=1, max_length=1000)]
    description: Annotated[str, Field(max_length=2000)] = ""


class TaskInputQuestion(Contract):
    question: Annotated[str, Field(min_length=1, max_length=2000)]
    description: Annotated[str, Field(max_length=4000)] = ""
    multi_select: bool = False
    options: tuple[TaskInputOption, ...] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def validate_options(self) -> TaskInputQuestion:
        if len({option.label for option in self.options}) != len(self.options):
            raise ValueError("input option labels must be unique")
        return self


class TaskInputRequest(Contract):
    request_id: Identity
    title: Annotated[str, Field(max_length=2000)] = ""
    questions: tuple[TaskInputQuestion, ...] = Field(
        min_length=1,
        max_length=4,
    )

    @model_validator(mode="after")
    def validate_questions(self) -> TaskInputRequest:
        canonical_json(
            [question.model_dump(mode="json") for question in self.questions],
        )
        return self


class TaskAnswer(Contract):
    question: Annotated[str, Field(min_length=1, max_length=2000)]
    selected_options: tuple[
        Annotated[str, Field(min_length=1, max_length=1000)],
        ...,
    ] = ()
    custom_text: Annotated[str, Field(max_length=4000)] | None = None

    @model_validator(mode="after")
    def validate_answer(self) -> TaskAnswer:
        if not self.selected_options and not (self.custom_text or "").strip():
            raise ValueError("an answer requires a selection or custom text")
        if len(set(self.selected_options)) != len(self.selected_options):
            raise ValueError("selected options must be unique")
        return self


class TaskCommand(Contract):
    protocol_version: Literal[1] = 1
    task_id: Identity
    command_id: Identity
    kind: Literal["answer", "cancel"]
    request_id: Identity | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    state: CommandState = "prepared"
    reason: Identity | None = None
    created_at: float
    updated_at: float

    @model_validator(mode="after")
    def validate_command(self) -> TaskCommand:
        canonical_json(self.payload)
        if self.kind == "answer":
            if not self.request_id or not isinstance(
                self.payload.get("answers"),
                list,
            ):
                raise ValueError(
                    "answer commands require request_id and answers",
                )
        elif self.request_id is not None or set(self.payload) - {"reason"}:
            raise ValueError("cancel commands accept only a reason")
        if self.state == "rejected" and not self.reason:
            raise ValueError("rejected commands require a reason")
        return self


class TaskHandle(Contract):
    schema_version: Literal[1] = 1
    task_id: Identity
    submission_id: Identity
    scope: TaskScope
    action_id: Identity
    descriptor_digest: Identity
    origin: TaskOrigin
    status: TaskStatus = "pending"
    submission_state: Literal["prepared", "in_flight", "accepted"] = "prepared"
    recovery_state: RecoveryState = "none"
    recovery_reason: str | None = None
    executor_run_ref: ExecutorRunRef | None = None
    replay_cursor: str | None = None
    executor_sequence: int | None = Field(default=None, ge=0)
    event_sequence: int = Field(default=0, ge=0)
    text_result: str | None = None
    output_refs: tuple[ArtifactRef, ...] = ()
    project_ref: ProjectRef | None = None
    input_request: TaskInputRequest | None = None
    cancel_requested: bool = False
    created_at: float
    updated_at: float


class TaskSubmission(Contract):
    """Durable envelope; reuse its identity after uncertain sends."""

    handle: TaskHandle
    action: ActionDescriptor
    inputs: dict[str, Any]


class ExecutorEvent(Contract):
    """Ordered executor event; cursor and effects are committed together."""

    run_ref: ExecutorRunRef
    sequence: int = Field(ge=0)
    cursor: Identity
    status: TaskStatus | None = None
    # A complete text snapshot, not a delta. Prior snapshots remain in events.
    text_result: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class TaskEvent(Contract):
    task_id: Identity
    sequence: int = Field(ge=1)
    kind: Literal["created", "submission", "executor", "recovery", "command"]
    status: TaskStatus
    payload: dict[str, Any]
    created_at: float


class TaskDelivery(Contract):
    """Outbox intent; acknowledging it requires a durable consumer receipt."""

    task_id: Identity
    event_sequence: int = Field(ge=1)
    kind: Literal["update", "continuation"]
    target_ref: Identity


class TaskStoreError(Exception):
    """Stable machine-readable storage errors without task input values."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
