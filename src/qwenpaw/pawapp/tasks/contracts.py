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
ANSWERABLE_STATUSES = frozenset(
    {"waiting_for_input", "waiting_for_approval"},
)
RecoveryState = Literal["none", "reconciling", "unresolved"]
CommandState = Literal[
    "prepared",
    "in_flight",
    "accepted",
    "rejected",
    "unknown",
]
CapabilityRisk = Literal["read", "write", "generation", "analysis", "other"]
ExperienceStepStatus = Literal[
    "pending",
    "running",
    "waiting",
    "complete",
    "failed",
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


class ArtifactPresentation(Contract):
    """App hint for presenting a published artifact outside its workspace.

    Publication and presentation are deliberately separate: every published
    artifact remains available in the explicit artifact library and handoff,
    while the Host may show only the business-relevant subset in Main Chat.
    """

    schema_version: Literal[1] = 1
    role: Literal["primary", "supporting", "diagnostic", "source"]
    kind: Annotated[
        str,
        Field(
            min_length=3,
            max_length=128,
            pattern=r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$",
        ),
    ]
    visibility: Literal["chat", "app_only"] = "chat"
    preview: Literal["inline", "link", "none"] = "link"
    rank: int = Field(default=100, ge=0, le=10000)


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
    presentation: ArtifactPresentation | None = None
    created_at: float


class ArtifactCollection(Contract):
    """A bounded, scoped view of Host-published artifact versions.

    Apps may project this generic collection into a richer library later, but
    the Host owns the stable paging and authorization envelope.
    """

    schema_version: Literal[1] = 1
    source: Literal["host_artifacts"] = "host_artifacts"
    app_id: Identity
    items: tuple[ArtifactRef, ...] = ()
    total_count: int = Field(ge=0)
    next_cursor: Identity | None = None


class ProjectRef(Contract):
    """Reference to an App-owned mutable project at a known revision."""

    schema_version: Literal[1] = 1
    app_id: Identity
    project_id: Identity
    kind: Identity
    revision: int = Field(ge=1)


class LocalizedText(Contract):
    """Bounded app-owned display copy with a deterministic fallback."""

    default: Annotated[str, Field(min_length=1, max_length=1000)]
    translations: dict[
        Annotated[str, Field(min_length=2, max_length=35)],
        Annotated[str, Field(min_length=1, max_length=1000)],
    ] = Field(default_factory=dict, max_length=16)

    @model_validator(mode="after")
    def validate_translations(self) -> LocalizedText:
        canonical_json(self.translations)
        return self


class TaskExperienceStepDefinition(Contract):
    id: Identity
    label: LocalizedText
    description: LocalizedText | None = None


class TaskExperienceViewDefinition(Contract):
    """App-owned destination resolved from the authenticated handoff."""

    id: Identity
    label: LocalizedText
    open_label: LocalizedText


class TaskExperienceDefinition(Contract):
    """Static display language registered separately from authorization."""

    schema_version: Literal[1] = 1
    action_id: Identity
    title: LocalizedText
    steps: tuple[TaskExperienceStepDefinition, ...] = Field(
        min_length=1,
        max_length=12,
    )
    views: tuple[TaskExperienceViewDefinition, ...] = Field(
        default=(),
        max_length=8,
    )
    default_view_id: Identity | None = None

    @model_validator(mode="after")
    def validate_definition(self) -> TaskExperienceDefinition:
        step_ids = [step.id for step in self.steps]
        view_ids = [view.id for view in self.views]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("experience step ids must be unique")
        if len(view_ids) != len(set(view_ids)):
            raise ValueError("experience view ids must be unique")
        if self.default_view_id is not None and (
            self.default_view_id not in view_ids
        ):
            raise ValueError("default experience view must be declared")
        return self

    @property
    def definition_digest(self) -> str:
        return content_digest(self.model_dump(mode="json"))


class TaskExperienceStepState(Contract):
    step_id: Identity
    status: ExperienceStepStatus
    progress: float | None = Field(default=None, ge=0, le=1)


class TaskExperienceContextItem(Contract):
    id: Identity
    label: LocalizedText
    value: Annotated[str, Field(min_length=1, max_length=1000)]


class TaskExperienceUpdate(Contract):
    """Mutable app projection. Stable IDs, rather than copy, drive behavior."""

    schema_version: Literal[1] = 1
    step_states: tuple[TaskExperienceStepState, ...] = Field(
        default=(),
        max_length=12,
    )
    active_step_id: Identity | None = None
    context_items: tuple[TaskExperienceContextItem, ...] | None = Field(
        default=None,
        max_length=12,
    )
    view_id: Identity | None = None

    @model_validator(mode="after")
    def validate_update(self) -> TaskExperienceUpdate:
        if len({state.step_id for state in self.step_states}) != len(
            self.step_states,
        ):
            raise ValueError("experience update step ids must be unique")
        if self.context_items is not None and len(
            {item.id for item in self.context_items},
        ) != len(self.context_items):
            raise ValueError("experience context ids must be unique")
        return self


class TaskExperienceSnapshot(Contract):
    schema_version: Literal[1] = 1
    definition: TaskExperienceDefinition
    definition_digest: Identity
    step_states: tuple[TaskExperienceStepState, ...]
    active_step_id: Identity | None = None
    context_items: tuple[TaskExperienceContextItem, ...] = Field(
        default=(),
        max_length=12,
    )
    view_id: Identity | None = None

    @model_validator(mode="after")
    def validate_snapshot(self) -> TaskExperienceSnapshot:
        if self.definition_digest != self.definition.definition_digest:
            raise ValueError("experience definition digest mismatch")
        expected = [step.id for step in self.definition.steps]
        actual = [state.step_id for state in self.step_states]
        if actual != expected:
            raise ValueError("experience snapshot must contain declared steps")
        if (
            self.active_step_id is not None
            and self.active_step_id not in actual
        ):
            raise ValueError("active experience step must be declared")
        view_ids = {view.id for view in self.definition.views}
        if self.view_id is not None and self.view_id not in view_ids:
            raise ValueError("experience view must be declared")
        if len({item.id for item in self.context_items}) != len(
            self.context_items,
        ):
            raise ValueError("experience context ids must be unique")
        return self


def initial_experience(
    definition: TaskExperienceDefinition,
) -> TaskExperienceSnapshot:
    return TaskExperienceSnapshot(
        definition=definition,
        definition_digest=definition.definition_digest,
        step_states=tuple(
            TaskExperienceStepState(step_id=step.id, status="pending")
            for step in definition.steps
        ),
        view_id=definition.default_view_id,
    )


def apply_experience_update(
    snapshot: TaskExperienceSnapshot,
    update: TaskExperienceUpdate,
) -> TaskExperienceSnapshot:
    declared_steps = {step.id for step in snapshot.definition.steps}
    incoming_steps = {state.step_id for state in update.step_states}
    if not incoming_steps <= declared_steps:
        raise ValueError("experience update contains undeclared steps")
    if (
        update.active_step_id is not None
        and update.active_step_id not in declared_steps
    ):
        raise ValueError("experience update has undeclared active step")
    declared_views = {view.id for view in snapshot.definition.views}
    if update.view_id is not None and update.view_id not in declared_views:
        raise ValueError("experience update has undeclared view")
    replacements = {state.step_id: state for state in update.step_states}
    return snapshot.model_copy(
        update={
            "step_states": tuple(
                replacements.get(state.step_id, state)
                for state in snapshot.step_states
            ),
            "active_step_id": (
                update.active_step_id
                if update.active_step_id is not None
                else snapshot.active_step_id
            ),
            "context_items": (
                update.context_items
                if update.context_items is not None
                else snapshot.context_items
            ),
            "view_id": (
                update.view_id
                if update.view_id is not None
                else snapshot.view_id
            ),
        },
    )


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


class TaskSetupNeed(Contract):
    requirement_id: Identity
    reason_code: Identity
    reason: Annotated[str, Field(min_length=1, max_length=1000)]


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
    experience: TaskExperienceSnapshot | None = None
    input_request: TaskInputRequest | None = None
    setup_request_id: Identity | None = None
    setup_attempt: int = Field(default=0, ge=0)
    cancel_requested: bool = False
    created_at: float
    updated_at: float

    @model_validator(mode="after")
    def validate_setup_link(self) -> TaskHandle:
        if self.setup_request_id is not None and (
            self.status != "waiting_for_setup" or self.setup_attempt < 1
        ):
            raise ValueError(
                "setup request links require a waiting task and positive "
                "attempt",
            )
        return self


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
    setup_need: TaskSetupNeed | None = None
    detail: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_setup_need(self) -> ExecutorEvent:
        if self.setup_need is not None and self.status != "waiting_for_setup":
            raise ValueError("setup needs require waiting_for_setup status")
        return self


class TaskEvent(Contract):
    task_id: Identity
    sequence: int = Field(ge=1)
    kind: Literal[
        "created",
        "submission",
        "executor",
        "recovery",
        "command",
        "setup",
    ]
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
