# -*- coding: utf-8 -*-
"""Public Creator video-workflow contract and deterministic goal mapping."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import math
import re
import time
from typing import Any, Literal

from domain.enums import (
    CreatorGoalStatus,
    CreatorSessionStatus,
    SpecialistRunStatus,
    TaskKind,
    TaskStatus,
    TERMINAL_SPECIALIST_STATUSES,
)
from models.config import (
    EXECUTION_AUTHORIZATION_ALLOW_ALL,
    MEDIA_REVIEW_AUTO_APPROVE,
    get_execution_authorization_mode,
    get_image_model_name,
    get_media_review_mode,
    get_video_model_name,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from schemas.projects import ProjectCreateRequest
from services.file_agent_runtime import (
    cancel_correlated_creator_agent_runtime,
    notify_creator_agent_runtime,
)
from services.execution_authorization import (
    decide_execution_authorization,
    execution_provider_model,
)
from services.file_agent_runtime.models import (
    AgentRunStatus,
    CreatorAgentRunRecord,
)
from services.file_agent_runtime.notifications import NOTIFICATION_SOURCE
from services.file_agent_runtime.run_store import (
    AgentRunStateConflict,
    CreatorAgentRunStore,
)
from services.file_agent_runtime.work_graph import (
    WorkGraph,
    WorkNode,
    WorkNodeStatus,
    derive_work_graph,
    dispatch_ledger_fingerprint,
    dispatch_model_scope,
    dispatch_slot,
)
from services.file_agent_runtime.workgraph_execution import requested_work_node
from services.pawapp_artifacts import (
    CreatorArtifactMismatch,
    CreatorArtifactUnavailable,
    read_verified_creator_artifact,
)
from services.project_files.creation import ProjectCreationResult
from services.project_files.facade import CreatorFileServices
from services.project_files.final_film import resolve_canonical_final_film
from services.project_files.models import Project, narrative_timeline_ids
from services.project_files.store import ProjectSnapshot
from services.runtime_files.atomic_store import AtomicJsonRecordStore
from services.runtime_files.execution_models import (
    ExecutionAuthorizationRecord,
    ExecutionAuthorizationStatus,
    SpecialistRunRecord,
    TaskRecord,
)
from services.runtime_files.execution_store import (
    ExecutionStateConflict,
    ProjectExecutionStore,
)
from services.runtime_files.models import (
    CreatorGoalRecord,
    CreatorMessageRecord,
    CreatorSessionRecord,
    utc_now,
)
from services.runtime_files.path_safety import require_safe_runtime_segment
from services.runtime_files.session_store import SessionStateConflict
from services.setup_coordination import (
    IMAGE_REQUIREMENT_ID,
    VIDEO_REQUIREMENT_ID,
)

from qwenpaw.pawapp.tasks import (
    ActionDescriptor,
    ArtifactRef,
    CommandLookup,
    ExecutorEvent,
    ExecutorRunRef,
    LocalizedText,
    SubmissionLookup,
    TaskAnswer,
    TaskCommand,
    TaskExperienceContextItem,
    TaskExperienceDefinition,
    TaskExperienceStepDefinition,
    TaskExperienceStepState,
    TaskExperienceUpdate,
    TaskExperienceViewDefinition,
    TaskInputOption,
    TaskInputQuestion,
    TaskInputRequest,
    TaskScope,
    TaskSetupNeed,
    TaskStoreError,
    TaskSubmission,
)
from qwenpaw.pawapp.tasks.binding import Readiness
from qwenpaw.pawapp.tasks.contracts import content_digest

CREATOR_VIDEO_GOAL_MAPPING_VERSION = 1

_CREATOR_APP_ID = "qwenpaw-creator"
_CREATE_VIDEO_ACTION_ID = "create-video"
CREATOR_VIDEO_WORKFLOW_EXECUTOR_ID = "qwenpaw-creator.video-workflow"
_MAX_WORKFLOW_EVENTS = 64
_WHITESPACE_RUN = re.compile(r"\s+")


class CreatorVideoWorkflowInput(BaseModel):
    """Strict, normalized intent-level input for one Creator workflow."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
    )

    brief: str = Field(min_length=1, max_length=8000, pattern=r"\S")
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        pattern=r"\S",
    )
    script: str | None = Field(
        default=None,
        min_length=1,
        max_length=50000,
        pattern=r"\S",
    )
    description: str = Field(default="", max_length=2000)
    scenario: Literal["short_drama", "video_edit", "general"] = "general"
    aspect_ratio: Literal["16:9", "9:16", "1:1", "4:3", "3:4"] = "16:9"
    resolution: Literal["720P", "1080P"] = "720P"
    content_type: (
        Literal[
            "pet_video",
            "gaming",
            "sports",
            "travel_vlog",
            "interview",
            "general",
        ]
        | None
    ) = None
    duration_seconds: StrictInt | None = Field(default=None, ge=1, le=3600)
    language: str = Field(
        default="zh-CN",
        min_length=2,
        max_length=35,
        pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$",
    )

    @field_validator(
        "brief",
        "name",
        "script",
        "description",
        "scenario",
        "aspect_ratio",
        "resolution",
        "content_type",
        "language",
        mode="before",
    )
    @classmethod
    def normalize_string(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def normalize_creator_video_workflow_input(
    inputs: Mapping[str, Any],
) -> CreatorVideoWorkflowInput:
    """Apply v1 normalization/defaults and reject non-contract input."""

    if not isinstance(inputs, Mapping):
        raise TypeError("Creator video workflow input must be a mapping")
    return CreatorVideoWorkflowInput.model_validate(dict(inputs))


def derive_creator_video_project_name(
    normalized_input: CreatorVideoWorkflowInput,
    submission_id: str,
) -> str:
    """Resolve the explicit or deterministic project name for a submission."""

    if normalized_input.name is not None:
        return normalized_input.name
    if not isinstance(submission_id, str) or not submission_id:
        raise ValueError("submission_id is required")

    first_line = next(
        (line for line in normalized_input.brief.splitlines() if line.strip()),
        None,
    )
    if first_line is None:
        raise ValueError("normalized brief has no non-empty line")
    readable = _WHITESPACE_RUN.sub(" ", first_line).strip()
    readable = readable[:96].rstrip(" ")
    if not readable:
        raise ValueError("normalized brief has no readable first line")
    suffix = "-" + sha256(submission_id.encode("utf-8")).hexdigest()[:12]
    resolved = readable + suffix
    if len(resolved) > 120:
        raise ValueError("derived project name exceeds 120 code points")
    return resolved


def render_creator_video_goal_v1(
    normalized_input: CreatorVideoWorkflowInput,
    submission_id: str,
) -> str:
    """Render the immutable v1 initial goal without a trailing newline."""

    project_name = derive_creator_video_project_name(
        normalized_input,
        submission_id,
    )
    script = normalized_input.script or (
        "Not provided; create a script from the brief."
    )
    description = normalized_input.description or "Not provided."
    content_type = normalized_input.content_type or "Not specified."
    duration = (
        str(normalized_input.duration_seconds)
        if normalized_input.duration_seconds is not None
        else "Not specified."
    )
    return (
        "[creator-video-workflow@1]\n"
        f"Submission: {submission_id}\n"
        "\n"
        "Brief:\n"
        f"{normalized_input.brief}\n"
        "\n"
        "User script:\n"
        f"{script}\n"
        "\n"
        "Production constraints:\n"
        f"- project_name: {project_name}\n"
        f"- description: {description}\n"
        f"- scenario: {normalized_input.scenario}\n"
        f"- aspect_ratio: {normalized_input.aspect_ratio}\n"
        f"- resolution: {normalized_input.resolution}\n"
        f"- content_type: {content_type}\n"
        f"- duration_seconds: {duration}\n"
        f"- language: {normalized_input.language}\n"
        "- completion: publish one final composed video"
    )


def creator_video_goal_digest_v1(
    normalized_input: CreatorVideoWorkflowInput,
    submission_id: str,
) -> str:
    """Digest the exact v1 rendered goal with Host canonical JSON rules."""

    return content_digest(
        render_creator_video_goal_v1(normalized_input, submission_id),
    )


def creator_create_video_action_descriptor() -> ActionDescriptor:
    """Describe the public delegated Creator video workflow."""

    return ActionDescriptor(
        app_id=_CREATOR_APP_ID,
        action_id=_CREATE_VIDEO_ACTION_ID,
        summary=(
            "Unlike create-project, which creates an empty project, "
            "create-video creates a Creator project, builds a production "
            "plan from the brief and optional script, pauses for required "
            "setup and generation approval, renders and publishes the final "
            "video, and returns the project and result."
        ),
        engagements=("delegated",),
        input_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "brief": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 8000,
                    "pattern": r"\S",
                },
                "name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 120,
                    "pattern": r"\S",
                },
                "script": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 50000,
                    "pattern": r"\S",
                },
                "description": {
                    "type": "string",
                    "maxLength": 2000,
                    "default": "",
                },
                "scenario": {
                    "type": "string",
                    "enum": ["short_drama", "video_edit", "general"],
                    "default": "general",
                },
                "aspect_ratio": {
                    "type": "string",
                    "enum": ["16:9", "9:16", "1:1", "4:3", "3:4"],
                    "default": "16:9",
                },
                "resolution": {
                    "type": "string",
                    "enum": ["720P", "1080P"],
                    "default": "720P",
                },
                "content_type": {
                    "type": "string",
                    "enum": [
                        "pet_video",
                        "gaming",
                        "sports",
                        "travel_vlog",
                        "interview",
                        "general",
                    ],
                },
                "duration_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 3600,
                },
                "language": {
                    "type": "string",
                    "minLength": 2,
                    "maxLength": 35,
                    "pattern": (r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$"),
                    "default": "zh-CN",
                },
            },
            "required": ["brief"],
            "additionalProperties": False,
        },
        output_types=("text/plain", "qwenpaw:file"),
        permissions=(
            "creator.project.create",
            "creator.project.read",
            "creator.project.write",
            "creator.image.generate",
            "creator.video.generate",
        ),
        effects=("model_usage", "project_mutation"),
        adapter_ref="qwenpaw-creator.video-workflow.v1",
    )


def creator_create_video_experience() -> TaskExperienceDefinition:
    """App-owned display language; intentionally outside the grant digest."""

    def text(default: str, zh: str) -> LocalizedText:
        return LocalizedText(default=default, translations={"zh-CN": zh})

    return TaskExperienceDefinition(
        action_id=_CREATE_VIDEO_ACTION_ID,
        title=text("Create a video", "创作视频"),
        steps=tuple(
            TaskExperienceStepDefinition(id=step_id, label=text(en, zh))
            for step_id, en, zh in (
                ("plan", "Plan", "策划"),
                ("storyboard", "Storyboard", "分镜"),
                ("generate", "Generate media", "生成素材"),
                ("compose", "Compose", "合成"),
                ("publish", "Publish", "发布"),
            )
        ),
        views=(
            TaskExperienceViewDefinition(
                id="project",
                label=text("Project", "项目"),
                open_label=text("Open project", "打开项目"),
            ),
            TaskExperienceViewDefinition(
                id="preview",
                label=text("Preview", "预览"),
                open_label=text("Open preview", "打开预览"),
            ),
            TaskExperienceViewDefinition(
                id="generation_details",
                label=text("Generation details", "生成详情"),
                open_label=text("View generation details", "查看生成详情"),
            ),
        ),
        default_view_id="project",
    )


CreatorVideoWorkflowStage = Literal[
    "prepared",
    "bootstrapping",
    "planning",
    "waiting_setup",
    "waiting_approval",
    "storyboarding",
    "generating_video",
    "composing",
    "publishing",
    "succeeded",
    "failed",
    "cancelled",
]

_WorkflowEventStatus = Literal[
    "pending",
    "running",
    "waiting_for_setup",
    "waiting_for_approval",
    "succeeded",
    "failed",
    "cancelled",
]
_EVENT_STATUS_BY_STAGE: dict[str, str] = {
    "prepared": "pending",
    "bootstrapping": "running",
    "planning": "running",
    "waiting_setup": "waiting_for_setup",
    "waiting_approval": "waiting_for_approval",
    "storyboarding": "running",
    "generating_video": "running",
    "composing": "running",
    "publishing": "running",
    "succeeded": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
}
_TERMINAL_WORKFLOW_STAGES = frozenset({"succeeded", "failed", "cancelled"})


class _FrozenWorkflowModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_default=True,
        revalidate_instances="always",
    )


class CreatorVideoWorkflowEvent(_FrozenWorkflowModel):
    """One bounded semantic workflow transition replayed to the Host."""

    schema_version: Literal[1] = 1
    sequence: StrictInt = Field(ge=0)
    cursor: str = Field(min_length=1, max_length=256)
    stage: CreatorVideoWorkflowStage
    status: _WorkflowEventStatus
    text_result: str = Field(min_length=1, max_length=1000, pattern=r"\S")
    evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    setup_requirement_id: (
        Literal[
            "storyboard-image",
            "shot-video",
        ]
        | None
    ) = None
    approval_request_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )
    created_at: float = Field(default_factory=time.time, ge=0)

    @model_validator(mode="after")
    def validate_stage_status(self) -> CreatorVideoWorkflowEvent:
        if self.status != _EVENT_STATUS_BY_STAGE[self.stage]:
            raise ValueError("workflow event status does not match its stage")
        if self.setup_requirement_id is not None and self.status != "running":
            raise ValueError("setup requirements require active workflow work")
        if (
            self.approval_request_id is not None
            and self.stage != "waiting_approval"
        ):
            raise ValueError("approval requests require waiting_approval")
        if (
            self.setup_requirement_id is not None
            and self.approval_request_id is not None
        ):
            raise ValueError(
                "setup and approval requests are mutually exclusive",
            )
        return self


class CreatorVideoSourceReceipt(_FrozenWorkflowModel):
    """Immutable Creator source selected at the publication boundary."""

    schema_version: Literal[1] = 1
    project_generation: StrictInt = Field(ge=0)
    project_etag: str = Field(min_length=1, max_length=256)
    timeline_id: str = Field(min_length=1, max_length=256)
    compose_fingerprint: str = Field(min_length=1, max_length=256)
    render_fingerprint: str = Field(min_length=1, max_length=256)
    artifact_version_id: str = Field(min_length=1, max_length=256)
    slot_id: str = Field(min_length=1, max_length=256)
    file_id: str = Field(min_length=1, max_length=256)
    name: str = Field(max_length=4096)
    relative_uri: str = Field(min_length=1, max_length=4096)
    media_type: str = Field(min_length=1, max_length=256)
    size_bytes: StrictInt = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    owner_ref: str = Field(min_length=1, max_length=512)
    producer_task_id: str = Field(min_length=1, max_length=256)
    producer_run_id: str = Field(min_length=1, max_length=256)
    read_set: tuple[dict[str, Any], ...] = Field(default=(), max_length=4096)
    source_selections: tuple[dict[str, Any], ...] = Field(
        default=(),
        max_length=4096,
    )

    @field_validator("read_set", "source_selections", mode="before")
    @classmethod
    def restore_mapping_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @property
    def receipt_digest(self) -> str:
        return content_digest(self.model_dump(mode="json"))

    @property
    def canonical_digest(self) -> str:
        payload = self.model_dump(
            mode="json",
            exclude={"project_generation", "project_etag"},
        )
        return content_digest(payload)


class CreatorVideoPublicationReceipt(_FrozenWorkflowModel):
    """Durable Host publication intent and its reconciliation state."""

    schema_version: Literal[1] = 1
    intent_id: str = Field(min_length=1, max_length=256)
    source_receipt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["intent", "published", "superseded"] = "intent"
    artifact_ref: ArtifactRef | None = None
    published_at: float | None = Field(default=None, ge=0)
    validated_project_generation: StrictInt | None = Field(
        default=None,
        ge=0,
    )
    validated_project_etag: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )
    superseded_at: float | None = Field(default=None, ge=0)
    superseded_reason: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_publication_state(self) -> CreatorVideoPublicationReceipt:
        has_artifact = self.artifact_ref is not None
        has_published_at = self.published_at is not None
        if has_artifact != has_published_at:
            raise ValueError("publication data fields are all-or-none")
        published = has_artifact and has_published_at
        validated = (
            self.validated_project_generation is not None
            and self.validated_project_etag is not None
        )
        superseded = (
            self.superseded_at is not None
            and self.superseded_reason is not None
        )
        if self.state == "intent" and (published or validated or superseded):
            raise ValueError("publication intent cannot carry terminal state")
        if self.state == "published" and (not published or superseded):
            raise ValueError(
                "published receipt requires only publication data",
            )
        if self.state == "superseded" and (not superseded or validated):
            raise ValueError("superseded receipt requires supersession data")
        if validated and self.state != "published":
            raise ValueError("only published receipts may be validated")
        if (self.validated_project_generation is None) != (
            self.validated_project_etag is None
        ):
            raise ValueError("publication validation fields are all-or-none")
        return self


class CreatorVideoWorkflowSubmission(_FrozenWorkflowModel):
    """Durable, identity-bound admission record for one Host submission."""

    schema_version: Literal[1] = 1
    task_id: str = Field(min_length=1, max_length=256)
    submission_id: str = Field(min_length=1, max_length=192)
    descriptor_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalized_input: CreatorVideoWorkflowInput
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    meaning_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    goal_mapping_version: Literal[1] = CREATOR_VIDEO_GOAL_MAPPING_VERSION
    goal_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_id: str = Field(min_length=1, max_length=192)
    creator_session_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=192,
    )
    conversation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=192,
    )
    goal_id: str | None = Field(default=None, min_length=1, max_length=192)
    initial_message_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )
    stage: CreatorVideoWorkflowStage = "prepared"
    setup_request_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )
    approval_request_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )
    correlated_goal_ids: tuple[str, ...] = Field(
        default=(),
        max_length=256,
    )
    correlated_run_ids: tuple[str, ...] = Field(
        default=(),
        max_length=256,
    )
    correlated_round_ids: tuple[str, ...] = Field(
        default=(),
        max_length=256,
    )
    correlated_task_ids: tuple[str, ...] = Field(
        default=(),
        max_length=1024,
    )
    failure_code: str | None = Field(
        default=None,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9_.:-]*$",
    )
    publication_committed: bool = False
    source_receipt: CreatorVideoSourceReceipt | None = None
    publication: CreatorVideoPublicationReceipt | None = None
    superseded_publications: tuple[
        CreatorVideoPublicationReceipt,
        ...,
    ] = Field(default=(), max_length=32)
    events: tuple[CreatorVideoWorkflowEvent, ...] = Field(
        min_length=1,
        max_length=_MAX_WORKFLOW_EVENTS,
    )
    created_at: float = Field(default_factory=time.time, ge=0)
    updated_at: float = Field(default_factory=time.time, ge=0)

    @field_validator("events", "superseded_publications", mode="before")
    @classmethod
    def restore_event_tuple(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator(
        "correlated_goal_ids",
        "correlated_run_ids",
        "correlated_round_ids",
        "correlated_task_ids",
        mode="before",
    )
    @classmethod
    def restore_identity_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_workflow_state(self) -> CreatorVideoWorkflowSubmission:
        if self.updated_at < self.created_at:
            raise ValueError("workflow updated_at cannot precede created_at")
        first_sequence = self.events[0].sequence
        expected_sequences = list(
            range(first_sequence, first_sequence + len(self.events)),
        )
        if [event.sequence for event in self.events] != expected_sequences:
            raise ValueError("workflow event sequences must be contiguous")
        if (
            self.events[0].created_at < self.created_at
            or self.events[-1].created_at > self.updated_at
        ):
            raise ValueError("workflow events must fit aggregate timestamps")
        if self.events[-1].stage != self.stage:
            raise ValueError("workflow stage must match its latest event")
        for previous, current in zip(self.events, self.events[1:]):
            if current.created_at < previous.created_at:
                raise ValueError("workflow event timestamps must be monotonic")
            if previous.stage in _TERMINAL_WORKFLOW_STAGES:
                raise ValueError("terminal workflow events must be last")

        correlated_id_sets = (
            self.correlated_goal_ids,
            self.correlated_run_ids,
            self.correlated_round_ids,
            self.correlated_task_ids,
        )
        duplicate_ids = any(
            len(values) != len(set(values)) for values in correlated_id_sets
        )
        if duplicate_ids:
            raise ValueError("correlated workflow identities must be unique")
        empty_ids = any(not all(values) for values in correlated_id_sets)
        if empty_ids:
            raise ValueError(
                "correlated workflow identities must be non-empty",
            )

        identities = (
            self.creator_session_id,
            self.conversation_id,
            self.goal_id,
            self.initial_message_id,
        )
        if any(value is not None for value in identities) and not all(
            value is not None for value in identities
        ):
            raise ValueError("workflow Runtime identities are all-or-none")
        if (
            self.goal_id is not None
            and self.correlated_goal_ids
            and self.goal_id not in self.correlated_goal_ids
        ):
            raise ValueError("initial goal must remain correlated")
        if self.stage in {"prepared", "bootstrapping"} and any(
            value is not None for value in identities
        ):
            raise ValueError("pre-bootstrap workflow cannot bind Runtime IDs")
        if self.stage not in {
            "prepared",
            "bootstrapping",
            "failed",
            "cancelled",
        }:
            if not all(value is not None for value in identities):
                raise ValueError("bootstrapped workflow requires Runtime IDs")

        has_setup_request = self.setup_request_id is not None
        has_approval_request = self.approval_request_id is not None
        if has_setup_request and has_approval_request:
            raise ValueError("setup and approval waits are mutually exclusive")
        if (self.stage == "waiting_setup") != has_setup_request:
            raise ValueError("setup request must exactly match waiting_setup")
        if (self.stage == "waiting_approval") != has_approval_request:
            raise ValueError(
                "approval request must exactly match waiting_approval",
            )
        if (self.stage == "failed") != (self.failure_code is not None):
            raise ValueError("failure code must exactly match failed stage")

        if (self.source_receipt is None) != (self.publication is None):
            raise ValueError("publication source and intent are all-or-none")
        if self.publication is not None:
            if not self.publication_committed:
                raise ValueError("publication intent must commit the workflow")
            if (
                self.publication.source_receipt_digest
                != self.source_receipt.receipt_digest
            ):
                raise ValueError(
                    "publication intent must bind its source receipt",
                )
        if self.superseded_publications:
            if not self.publication_committed or any(
                item.state != "superseded"
                for item in self.superseded_publications
            ):
                raise ValueError("publication history must be superseded")
        if self.stage == "cancelled" and self.publication_committed:
            raise ValueError("publication-committed workflows cannot cancel")
        if self.stage == "publishing" and self.publication is None:
            raise ValueError("publishing requires a durable intent")
        if self.stage == "succeeded":
            if (
                self.publication is None
                or self.publication.state != "published"
                or self.publication.validated_project_generation is None
            ):
                raise ValueError("successful workflow requires publication")
        return self


_EVENT_TEXT: dict[str, str] = {
    "prepared": "Creator video workflow prepared.",
    "bootstrapping": "Creator is creating the video project.",
    "planning": "Creator is planning the video.",
    "waiting_setup": "Creator needs additional setup to continue.",
    "waiting_approval": "Creator is waiting for generation approval.",
    "storyboarding": "Creator is preparing the storyboard.",
    "generating_video": "Creator is generating the video.",
    "composing": "Creator is composing the final video.",
    "publishing": "Creator is publishing the final video.",
    "succeeded": "Creator finished and published the video.",
    "failed": "Creator could not complete the video.",
    "cancelled": "Creator video workflow was cancelled.",
}
_EXPERIENCE_STEPS = ("plan", "storyboard", "generate", "compose", "publish")
_EXPERIENCE_STEP_BY_STAGE = {
    "prepared": "plan",
    "bootstrapping": "plan",
    "planning": "plan",
    "storyboarding": "storyboard",
    "generating_video": "generate",
    "composing": "compose",
    "publishing": "publish",
    "succeeded": "publish",
}


def _creator_experience_update(
    submission: TaskSubmission,
    record: CreatorVideoWorkflowSubmission,
    workflow_event: CreatorVideoWorkflowEvent,
) -> TaskExperienceUpdate:
    stage = workflow_event.stage
    active = _EXPERIENCE_STEP_BY_STAGE.get(stage)
    if active is None:
        prior = next(
            (
                item.stage
                for item in reversed(record.events)
                if item.sequence < workflow_event.sequence
                and item.stage in _EXPERIENCE_STEP_BY_STAGE
            ),
            "planning",
        )
        active = _EXPERIENCE_STEP_BY_STAGE[prior]
    active_index = _EXPERIENCE_STEPS.index(active)
    terminal_success = stage == "succeeded"
    failed = stage in {"failed", "cancelled"}
    waiting = stage in {"waiting_setup", "waiting_approval"}
    states = []
    for index, step_id in enumerate(_EXPERIENCE_STEPS):
        if terminal_success or index < active_index:
            status = "complete"
        elif index > active_index:
            status = "pending"
        elif failed:
            status = "failed"
        elif waiting:
            status = "waiting"
        else:
            status = "running"
        states.append(TaskExperienceStepState(step_id=step_id, status=status))
    normalized = normalize_creator_video_workflow_input(submission.inputs)
    context = [
        TaskExperienceContextItem(
            id="resolution",
            label=LocalizedText(
                default="Resolution",
                translations={"zh-CN": "分辨率"},
            ),
            value=normalized.resolution,
        ),
        TaskExperienceContextItem(
            id="aspect_ratio",
            label=LocalizedText(
                default="Aspect ratio",
                translations={"zh-CN": "画面比例"},
            ),
            value=normalized.aspect_ratio,
        ),
    ]
    if normalized.duration_seconds is not None:
        context.append(
            TaskExperienceContextItem(
                id="duration",
                label=LocalizedText(
                    default="Target duration",
                    translations={"zh-CN": "目标时长"},
                ),
                value=f"{normalized.duration_seconds}s",
            ),
        )
    return TaskExperienceUpdate(
        step_states=tuple(states),
        active_step_id=active,
        context_items=tuple(context),
        view_id="preview" if terminal_success else "project",
    )


_SETUP_NEED = {
    IMAGE_REQUIREMENT_ID: (
        "creator_image_model_missing",
        "Configure and enable the Creator image generation model.",
    ),
    VIDEO_REQUIREMENT_ID: (
        "creator_video_model_missing",
        "Configure and enable the Creator video generation model.",
    ),
}
_APPROVAL_QUESTION = "Run this Creator generation operation once?"
_APPROVAL_OPERATION_LABELS = {
    "image_generation": "Generate storyboard imagery",
    "r2v_generation": "Generate a video shot",
    "s2v_generation": "Generate a lip-synced video shot",
    "tts_generation": "Generate narration or dialogue audio",
    "create_character_voice": "Create a character voice",
}
_APPROVAL_TARGET_LABELS = {
    "image_generation": "current storyboard visual",
    "r2v_generation": "current storyboard shot",
    "s2v_generation": "current speaking character shot",
    "tts_generation": "current narration or dialogue",
    "create_character_voice": "current character voice",
}
_APPROVAL_TEXT = re.compile(r"^[^\x00-\x1f\x7f]{1,120}$")
_APPROVAL_MODE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_APPROVAL_RATIO = re.compile(r"^[1-9]\d{0,3}:[1-9]\d{0,3}$")
_APPROVAL_RESOLUTION = re.compile(r"^(?:[1-9]\d{2,3}[Pp]|[1-9][Kk])$")


def _approval_identity(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = _WHITESPACE_RUN.sub(" ", value).strip()
    return normalized if _APPROVAL_TEXT.fullmatch(normalized) else fallback


def _approval_description(record: ExecutionAuthorizationRecord) -> str:
    operation = _APPROVAL_OPERATION_LABELS.get(
        record.operation,
        "Run a Creator production step",
    )
    target = _APPROVAL_TARGET_LABELS.get(record.operation, "current project")
    parts = [
        f"Operation: {operation}",
        f"Target: {target}",
        "Provider: "
        + _approval_identity(record.requested_provider, "configured provider"),
        "Model: "
        + _approval_identity(record.requested_model, "configured model"),
        f"Candidate count: {record.requested_candidates or 1}",
    ]
    scope = record.scope if isinstance(record.scope, Mapping) else {}
    raw_parameters = scope.get("parameters")
    parameters = raw_parameters if isinstance(raw_parameters, Mapping) else {}
    duration = parameters.get("durationSeconds")
    if (
        isinstance(duration, (int, float))
        and not isinstance(duration, bool)
        and math.isfinite(duration)
        and duration > 0
    ):
        parts.append(f"Duration: {duration:g} seconds")
    resolution = parameters.get("resolution")
    if isinstance(resolution, str) and _APPROVAL_RESOLUTION.fullmatch(
        resolution,
    ):
        parts.append(f"Resolution: {resolution.upper()}")
    ratio = parameters.get("ratio") or parameters.get("aspectRatio")
    if isinstance(ratio, str) and _APPROVAL_RATIO.fullmatch(ratio):
        parts.append(f"Aspect ratio: {ratio}")
    mode = parameters.get("mode")
    if isinstance(mode, str) and _APPROVAL_MODE.fullmatch(mode):
        parts.append(f"Mode: {mode}")
    generate_audio = parameters.get("generateAudio")
    if isinstance(generate_audio, bool):
        parts.append("Audio: " + ("enabled" if generate_audio else "disabled"))
    return ". ".join(parts) + "."


def _approval_request_id(
    workflow: CreatorVideoWorkflowSubmission,
    authorization: ExecutionAuthorizationRecord,
) -> str:
    digest = content_digest(
        {
            "domain": "qwenpaw:creator-video-approval",
            "version": 1,
            "submission_id": workflow.submission_id,
            "authorization_id": authorization.authorization_id,
            "execution_request_id": authorization.execution_request_id,
        },
    )
    return f"creator-approval-{digest[:32]}"


def _approval_input_request(
    workflow: CreatorVideoWorkflowSubmission,
    authorization: ExecutionAuthorizationRecord,
) -> TaskInputRequest:
    return TaskInputRequest(
        request_id=_approval_request_id(workflow, authorization),
        title="Creator generation approval",
        questions=(
            TaskInputQuestion(
                question=_APPROVAL_QUESTION,
                description=_approval_description(authorization),
                options=(
                    TaskInputOption(
                        label="Approve once",
                        description="Approve only this immutable request.",
                    ),
                    TaskInputOption(
                        label="Do not run",
                        description="Reject this request without starting it.",
                    ),
                ),
            ),
        ),
    )


def _workflow_event(
    stage: CreatorVideoWorkflowStage,
    sequence: int,
    *,
    evidence: Mapping[str, Any] | None = None,
    setup_requirement_id: str | None = None,
    approval_request_id: str | None = None,
    text_result: str | None = None,
    created_at: float | None = None,
) -> CreatorVideoWorkflowEvent:
    return CreatorVideoWorkflowEvent(
        sequence=sequence,
        cursor=f"creator-video-workflow-{sequence}-{stage}",
        stage=stage,
        status=_EVENT_STATUS_BY_STAGE[stage],
        text_result=text_result or _EVENT_TEXT[stage],
        evidence_digest=content_digest(dict(evidence or {"stage": stage})),
        setup_requirement_id=setup_requirement_id,
        approval_request_id=approval_request_id,
        created_at=time.time() if created_at is None else created_at,
    )


_RESUME_MESSAGE_SOURCES = frozenset(
    {
        "mainline_resume",
        "yolo_auto_resume",
        "prompt_contract_resume",
        NOTIFICATION_SOURCE,
    },
)
_RECOVERABLE_CANCELLATION_CODES = frozenset(
    {
        "DUPLICATE_ADMISSION",
        "ORPHANED_BY_RESTART",
        "SHUTDOWN",
        "SUPERSEDED",
    },
)
_STORYBOARD_KINDS = frozenset({"visual", "lineup", "storyboard"})
_ACTIVE_TASK_STATUSES = frozenset({TaskStatus.QUEUED, TaskStatus.RUNNING})


@dataclass(frozen=True, slots=True)
class _ObservedWorkflowState:
    stage: CreatorVideoWorkflowStage
    evidence: Mapping[str, Any]
    correlated_goal_ids: tuple[str, ...]
    correlated_run_ids: tuple[str, ...]
    correlated_round_ids: tuple[str, ...]
    correlated_task_ids: tuple[str, ...]
    setup_requirement_id: str | None = None
    approval_request_id: str | None = None
    failure_code: str | None = None
    source_receipt: CreatorVideoSourceReceipt | None = None


def _run_error_code(run: CreatorAgentRunRecord) -> str | None:
    error = run.error
    if not isinstance(error, Mapping):
        return None
    code = error.get("code")
    return code if isinstance(code, str) and code else None


def _correlated_agent_runs(
    record: CreatorVideoWorkflowSubmission,
    runs: Sequence[CreatorAgentRunRecord],
    messages: Sequence[CreatorMessageRecord],
    *,
    additional_message_ids: frozenset[str] = frozenset(),
) -> tuple[
    tuple[CreatorAgentRunRecord, ...],
    tuple[str, ...],
    frozenset[str],
    frozenset[int],
]:
    if (
        record.creator_session_id is None
        or record.conversation_id is None
        or record.goal_id is None
        or record.initial_message_id is None
    ):
        return (), (), frozenset(), frozenset()

    eligible_runs = tuple(
        run
        for run in runs
        if run.project_id == record.project_id
        and run.session_id == record.creator_session_id
        and run.conversation_id == record.conversation_id
    )
    eligible_messages = tuple(
        message
        for message in messages
        if message.project_id == record.project_id
        and message.creator_session_id == record.creator_session_id
        and message.conversation_id == record.conversation_id
    )
    goal_ids = {record.goal_id}
    message_ids = {record.initial_message_id, *additional_message_ids}
    message_sequences = {
        message.message_seq
        for message in eligible_messages
        if message.message_id in message_ids
    }
    run_ids: set[str] = set()

    changed = True
    while changed:
        changed = False
        for run in eligible_runs:
            if run.run_id in run_ids:
                continue
            if run.goal_id in goal_ids or (
                run.caused_by_message_id in message_ids
                or run.caused_by_message_seq in message_sequences
            ):
                run_ids.add(run.run_id)
                goal_ids.add(run.goal_id)
                changed = True
        for message in eligible_messages:
            if message.message_id in message_ids:
                continue
            if message.source not in _RESUME_MESSAGE_SOURCES:
                continue
            resume_after = message.metadata.get("resumeAfterRunId")
            interrupted = message.metadata.get("interruptedRunId")
            if resume_after in run_ids or interrupted in run_ids:
                message_ids.add(message.message_id)
                message_sequences.add(message.message_seq)
                changed = True

    correlated = tuple(run for run in eligible_runs if run.run_id in run_ids)
    ordered_goal_ids = (
        record.goal_id,
        *sorted(goal_ids - {record.goal_id}),
    )
    return (
        correlated,
        ordered_goal_ids,
        frozenset(message_ids),
        frozenset(message_sequences),
    )


def _correlated_specialist_runs(
    runs: Sequence[SpecialistRunRecord],
    *,
    agent_run_ids: frozenset[str],
    round_ids: frozenset[str],
) -> tuple[SpecialistRunRecord, ...]:
    correlated_ids: set[str] = set()
    changed = True
    while changed:
        changed = False
        for run in runs:
            parent_run_id = run.metadata.get("parentRunId")
            if run.run_id in correlated_ids:
                continue
            if (
                run.related_run_id in agent_run_ids
                or parent_run_id in agent_run_ids
                or run.round_id in round_ids
                or run.supersedes_run_id in correlated_ids
            ):
                correlated_ids.add(run.run_id)
                changed = True
    return tuple(run for run in runs if run.run_id in correlated_ids)


def _correlated_tasks(
    tasks: Sequence[TaskRecord],
    *,
    run_ids: frozenset[str],
    round_ids: frozenset[str],
    message_ids: frozenset[str],
    message_sequences: frozenset[int],
) -> tuple[TaskRecord, ...]:
    return tuple(
        task
        for task in tasks
        if task.run_id in run_ids
        or task.round_id in round_ids
        or task.caused_by_message_id in message_ids
        or task.caused_by_message_seq in message_sequences
    )


def _correlated_runtime_notifications(
    messages: Sequence[CreatorMessageRecord],
    *,
    specialist_run_ids: frozenset[str],
    tasks: Sequence[TaskRecord],
    graph: WorkGraph,
) -> frozenset[str]:
    task_ids = frozenset(task.task_id for task in tasks)
    task_request_ids = frozenset(
        request_id
        for task in tasks
        for request_id in (task.idempotency_key, task.caused_by_request_id)
        if request_id
    )
    node_by_id = graph.by_id
    linked: set[str] = set()
    for message in messages:
        if message.source != NOTIFICATION_SOURCE:
            continue
        metadata = message.metadata
        node_id = metadata.get("nodeId")
        node = node_by_id.get(node_id) if isinstance(node_id, str) else None
        if (
            metadata.get("specialistRunId") in specialist_run_ids
            or metadata.get("taskId") in task_ids
            or metadata.get("requestId") in task_request_ids
            or node is not None
            and node.task_id in task_ids
        ):
            linked.add(message.message_id)
    return frozenset(linked)


def _correlated_authorizations(
    authorizations: Sequence[ExecutionAuthorizationRecord],
    *,
    run_ids: frozenset[str],
    round_ids: frozenset[str],
    task_ids: frozenset[str],
    message_ids: frozenset[str],
    message_sequences: frozenset[int],
) -> tuple[ExecutionAuthorizationRecord, ...]:
    return tuple(
        authorization
        for authorization in authorizations
        if authorization.run_id in run_ids
        or authorization.round_id in round_ids
        or authorization.task_id in task_ids
        or authorization.metadata.get("parentRunId") in run_ids
        or authorization.caused_by_message_id in message_ids
        or authorization.caused_by_message_seq in message_sequences
    )


def _correlated_reviews(
    reviews: Sequence[Any],
    *,
    review_ids: frozenset[str],
    run_ids: frozenset[str],
    round_ids: frozenset[str],
) -> tuple[Any, ...]:
    return tuple(
        review
        for review in reviews
        if getattr(review, "review_id", None) in review_ids
        or getattr(review, "round_id", None) in round_ids
        or getattr(review, "interrupted_run_id", None) in run_ids
    )


def _automatic_regeneration_enabled() -> bool:
    authorization_mode = get_execution_authorization_mode()
    return (
        get_media_review_mode() == MEDIA_REVIEW_AUTO_APPROVE
        and authorization_mode == EXECUTION_AUTHORIZATION_ALLOW_ALL
    )


def _node_is_correlated_running(
    node: WorkNode,
    correlated_task_ids: frozenset[str],
) -> bool:
    return (
        node.status is WorkNodeStatus.RUNNING
        and node.task_id is not None
        and node.task_id in correlated_task_ids
    )


@dataclass(frozen=True, slots=True)
class _FinalSourceResolution:
    source_receipt: CreatorVideoSourceReceipt | None = None
    failure_code: str | None = None


def _resolve_final_source(
    snapshot: ProjectSnapshot,
    graph: WorkGraph,
    tasks: Sequence[TaskRecord],
) -> _FinalSourceResolution:
    live_timeline_ids = narrative_timeline_ids(snapshot.project)
    if len(live_timeline_ids) > 1:
        return _FinalSourceResolution(failure_code="multiple_live_timelines")
    if not live_timeline_ids:
        return _FinalSourceResolution()

    timeline_id = live_timeline_ids[0]
    compose_nodes = tuple(
        node
        for node in graph.nodes
        if node.kind == "compose" and node.timeline_id == timeline_id
    )
    if not compose_nodes or compose_nodes[0].status is not WorkNodeStatus.DONE:
        return _FinalSourceResolution()
    if len(compose_nodes) != 1:
        return _FinalSourceResolution(failure_code="final_source_invalid")
    compose = compose_nodes[0]
    final = resolve_canonical_final_film(snapshot.project)
    if final is None or not compose.dispatch_fingerprint:
        return _FinalSourceResolution(failure_code="final_source_invalid")

    task_id = final.version.metadata.get("taskId")
    run_id = final.version.metadata.get("runId")
    task = next(
        (
            item
            for item in tasks
            if item.task_id == task_id
            and item.status is TaskStatus.SUCCEEDED
            and item.kind is TaskKind.COMPOSE
        ),
        None,
    )
    source_selections = final.version.metadata.get("sourceSelections")
    compose_ledger = dispatch_ledger_fingerprint(
        compose.dispatch_fingerprint,
        dispatch_model_scope(compose.kind, ("", "")),
    )
    expected_dispatch_key = (
        f"dag-{compose.node_id}-{dispatch_slot(compose_ledger)}"
    )
    task_dispatch_key = task.idempotency_key if task is not None else None
    trusted_dispatch = bool(
        isinstance(task_dispatch_key, str)
        and (
            task_dispatch_key == expected_dispatch_key
            or re.fullmatch(
                rf"{re.escape(expected_dispatch_key)}-r[1-8]",
                task_dispatch_key,
            )
            is not None
        ),
    )
    if (
        task is None
        or not isinstance(task_id, str)
        or not isinstance(run_id, str)
        or not run_id
        or task.run_id != run_id
        or not trusted_dispatch
        or task.request_fingerprint != final.version.input_fingerprint
        or task.metadata.get("commandType") != "COMPOSE_FINAL_VIDEO"
        or task.metadata.get("targetRef") != f"timeline:{timeline_id}"
        or not isinstance(source_selections, list)
        or not all(isinstance(item, Mapping) for item in source_selections)
    ):
        return _FinalSourceResolution(failure_code="final_source_untrusted")

    try:
        source_receipt = CreatorVideoSourceReceipt(
            project_generation=snapshot.generation,
            project_etag=snapshot.etag,
            timeline_id=timeline_id,
            compose_fingerprint=compose.dispatch_fingerprint,
            render_fingerprint=task.request_fingerprint,
            artifact_version_id=final.version.version_id,
            slot_id=final.slot.slot_id,
            file_id=final.file.file_id,
            name=final.version.name,
            relative_uri=final.file.relative_uri,
            media_type=final.file.media_type,
            size_bytes=final.file.size_bytes,
            sha256=final.file.sha256,
            owner_ref=final.version.owner_ref,
            producer_task_id=task.task_id,
            producer_run_id=run_id,
            read_set=tuple(dict(item) for item in task.read_set),
            source_selections=tuple(dict(item) for item in source_selections),
        )
    except ValueError:
        return _FinalSourceResolution(failure_code="final_source_invalid")
    return _FinalSourceResolution(source_receipt=source_receipt)


def _publication_intent(
    record: CreatorVideoWorkflowSubmission,
    source: CreatorVideoSourceReceipt,
) -> CreatorVideoPublicationReceipt:
    digest = content_digest(
        {
            "domain": "qwenpaw:creator-video-publication",
            "version": 1,
            "task_id": record.task_id,
            "submission_id": record.submission_id,
            "source_receipt_digest": source.receipt_digest,
        },
    )
    return CreatorVideoPublicationReceipt(
        intent_id=f"creator-video-publication-{digest[:40]}",
        source_receipt_digest=source.receipt_digest,
    )


def _authorization_has_stale_execution_identity(
    authorization: ExecutionAuthorizationRecord,
    project_snapshot: ProjectSnapshot,
    graph: WorkGraph,
) -> bool:
    if len(authorization.target_scope) != 1:
        return False
    target_ref = authorization.target_scope[0]
    matched = False
    for node in graph.nodes:
        if node.target_ref != target_ref or node.command is None:
            continue
        try:
            plan = requested_work_node(project_snapshot, node)
        except ValueError:
            continue
        if plan.spec.name != authorization.operation:
            continue
        matched = True
        if execution_provider_model(plan.spec, plan.parameters) == (
            authorization.requested_provider,
            authorization.requested_model,
        ):
            return False
    return matched


def _expire_stale_pending_authorizations(
    executions: ProjectExecutionStore,
    project_snapshot: ProjectSnapshot,
    graph: WorkGraph,
    authorizations: Sequence[ExecutionAuthorizationRecord],
) -> tuple[tuple[ExecutionAuthorizationRecord, ...], bool]:
    pending: list[ExecutionAuthorizationRecord] = []
    expired = False
    for authorization in authorizations:
        if not _authorization_has_stale_execution_identity(
            authorization,
            project_snapshot,
            graph,
        ):
            pending.append(authorization)
            continue
        try:
            executions.decide_execution_authorization(
                authorization.project_id,
                authorization.authorization_id,
                authorization_token=authorization.authorization_token,
                status=ExecutionAuthorizationStatus.EXPIRED,
                metadata={
                    "expiredBy": "pawapp_video_workflow",
                    "reason": "execution_configuration_changed",
                },
            )
        except ExecutionStateConflict:
            current = executions.get_execution_authorization(
                authorization.project_id,
                authorization.authorization_id,
            )
            if current.status is ExecutionAuthorizationStatus.PENDING:
                pending.append(current)
        else:
            expired = True
    return tuple(pending), expired


def _classify_observed_state(
    *,
    record: CreatorVideoWorkflowSubmission,
    project_snapshot: ProjectSnapshot,
    session: CreatorSessionRecord,
    goals: Sequence[CreatorGoalRecord],
    agent_runs: Sequence[CreatorAgentRunRecord],
    specialist_runs: Sequence[SpecialistRunRecord],
    tasks: Sequence[TaskRecord],
    pending_authorizations: Sequence[ExecutionAuthorizationRecord],
    pending_reviews: Sequence[Any],
    pending_resume: bool,
    graph: WorkGraph,
    executor_sequence: int | None,
) -> _ObservedWorkflowState:
    goal_ids = tuple(goal.goal_id for goal in goals)
    agent_run_ids = tuple(run.run_id for run in agent_runs)
    specialist_run_ids = tuple(run.run_id for run in specialist_runs)
    run_ids = (*agent_run_ids, *specialist_run_ids)
    round_ids = tuple(
        dict.fromkeys(
            [run.round_id for run in agent_runs]
            + [run.round_id for run in specialist_runs],
        ),
    )
    task_ids = tuple(task.task_id for task in tasks)
    latest_run = agent_runs[-1] if agent_runs else None
    goals_by_id = {goal.goal_id: goal for goal in goals}
    latest_goal = (
        goals_by_id.get(latest_run.goal_id) if latest_run is not None else None
    ) or goals_by_id.get(record.goal_id or "")
    latest_error_code = None
    if latest_run is not None:
        latest_error_code = _run_error_code(latest_run)

    ready_nodes = graph.ready_media_nodes()
    regeneration_nodes = graph.regeneration_nodes()
    model_required_nodes = graph.model_required_nodes(
        automatic_regeneration=_automatic_regeneration_enabled(),
    )
    correlated_task_ids = frozenset(task_ids)
    running_nodes = tuple(
        node
        for node in graph.nodes
        if _node_is_correlated_running(node, correlated_task_ids)
    )
    active_statuses = _ACTIVE_TASK_STATUSES
    active_tasks = []
    for task in tasks:
        if task.status in active_statuses:
            active_tasks.append(task)
    terminal_specialist_statuses = TERMINAL_SPECIALIST_STATUSES
    active_specialists = []
    for run in specialist_runs:
        if run.status not in terminal_specialist_statuses:
            active_specialists.append(run)
    active_agent_runs = tuple(
        run
        for run in agent_runs
        if run.status in {AgentRunStatus.QUEUED, AgentRunStatus.RUNNING}
    )

    agent_evidence = []
    for run in agent_runs:
        agent_evidence.append(
            [run.run_id, run.status.value, _run_error_code(run)],
        )
    specialist_evidence = []
    for run in specialist_runs:
        specialist_evidence.append([run.run_id, run.status.value])
    task_evidence = []
    for task in tasks:
        task_evidence.append(
            [task.task_id, task.kind.value, task.status.value],
        )
    authorization_ids = []
    for authorization in pending_authorizations:
        authorization_ids.append(authorization.authorization_id)
    graph_evidence = []
    for node in graph.nodes:
        graph_evidence.append(
            [node.node_id, node.kind, node.status.value],
        )
    evidence: dict[str, Any] = {
        "project_generation": project_snapshot.generation,
        "session_status": session.status.value,
        "goals": [[goal.goal_id, goal.status.value] for goal in goals],
        "agent_runs": agent_evidence,
        "specialist_runs": specialist_evidence,
        "tasks": task_evidence,
        "pending_authorizations": authorization_ids,
        "pending_reviews": [
            getattr(review, "review_id", "") for review in pending_reviews
        ],
        "pending_resume": pending_resume,
        "graph": graph_evidence,
    }

    def observed(
        stage: CreatorVideoWorkflowStage,
        *,
        setup_requirement_id: str | None = None,
        approval_request_id: str | None = None,
        failure_code: str | None = None,
        source_receipt: CreatorVideoSourceReceipt | None = None,
    ) -> _ObservedWorkflowState:
        state_evidence = {**evidence, "stage": stage}
        if source_receipt is not None:
            state_evidence[
                "source_receipt_digest"
            ] = source_receipt.receipt_digest
        return _ObservedWorkflowState(
            stage=stage,
            evidence=state_evidence,
            correlated_goal_ids=goal_ids,
            correlated_run_ids=run_ids,
            correlated_round_ids=round_ids,
            correlated_task_ids=task_ids,
            setup_requirement_id=setup_requirement_id,
            approval_request_id=approval_request_id,
            failure_code=failure_code,
            source_receipt=source_receipt,
        )

    if record.publication is not None:
        return observed("publishing")

    recoverable_run_cancellation = bool(
        latest_run is not None
        and latest_run.status is AgentRunStatus.CANCELLED
        and latest_error_code in _RECOVERABLE_CANCELLATION_CODES,
    )
    if not record.publication_committed:
        if latest_run is not None:
            if (
                latest_run.status is AgentRunStatus.CANCELLED
                and not recoverable_run_cancellation
            ):
                return observed("cancelled")
        elif latest_goal is not None:
            if latest_goal.status is CreatorGoalStatus.CANCELLED:
                return observed("cancelled")
        if (
            not recoverable_run_cancellation
            and session.status is CreatorSessionStatus.CANCELLED
            and session.active_goal_id in set(goal_ids)
        ):
            return observed("cancelled")

    if record.stage == "waiting_setup" and record.setup_request_id is not None:
        return observed("waiting_setup")

    actionable_nodes = (*ready_nodes, *regeneration_nodes)
    working_nodes = (*running_nodes, *actionable_nodes)
    working_kinds = {node.kind for node in working_nodes}
    active_task_kinds = {task.kind for task in active_tasks}
    has_video_node = "video" in working_kinds
    has_video_task = TaskKind.R2V_GENERATION in active_task_kinds
    has_storyboard_node = not _STORYBOARD_KINDS.isdisjoint(working_kinds)
    has_image_task = TaskKind.IMAGE_GENERATION in active_task_kinds
    setup_requirement_id = None
    if has_storyboard_node or has_image_task:
        setup_requirement_id = IMAGE_REQUIREMENT_ID
    elif has_video_node or has_video_task:
        setup_requirement_id = VIDEO_REQUIREMENT_ID

    work_stage: CreatorVideoWorkflowStage | None = None
    if "compose" in working_kinds or TaskKind.COMPOSE in active_task_kinds:
        work_stage = "composing"
    elif has_video_node or has_video_task:
        work_stage = "generating_video"
    elif has_storyboard_node or has_image_task:
        work_stage = "storyboarding"

    if pending_authorizations:
        if setup_requirement_id is not None:
            if work_stage is None:
                raise TaskStoreError("creator_video_setup_stage_missing")
            consumed_sequence = (
                -1 if executor_sequence is None else executor_sequence
            )
            setup_was_checked = any(
                event.sequence <= consumed_sequence
                and event.setup_requirement_id == setup_requirement_id
                for event in record.events
            )
            if not setup_was_checked:
                return observed(
                    work_stage,
                    setup_requirement_id=setup_requirement_id,
                )
        return observed(
            "waiting_approval",
            approval_request_id=pending_authorizations[0].authorization_id,
        )

    recoverable = bool(
        pending_reviews
        or pending_resume
        or model_required_nodes
        or session.status
        in {
            CreatorSessionStatus.PENDING_REVIEW,
            CreatorSessionStatus.RESUMING,
            CreatorSessionStatus.WAITING_USER_INPUT,
            CreatorSessionStatus.WAITING_EXECUTION_AUTH,
        }
        or latest_goal is not None
        and latest_goal.status
        in {
            CreatorGoalStatus.WAITING_REVIEW,
            CreatorGoalStatus.RESUME_REQUIRED,
        },
    )
    final_source = _resolve_final_source(project_snapshot, graph, tasks)
    if final_source.source_receipt is not None:
        return observed(
            "publishing",
            source_receipt=final_source.source_receipt,
        )
    if final_source.failure_code == "multiple_live_timelines":
        if recoverable:
            return observed("planning")
        return observed("failed", failure_code=final_source.failure_code)

    if work_stage is not None:
        return observed(
            work_stage,
            setup_requirement_id=setup_requirement_id,
        )

    if active_tasks or active_specialists or running_nodes or actionable_nodes:
        return observed("planning")

    if recoverable or active_agent_runs:
        return observed("planning")

    initial_goal = goals_by_id.get(record.goal_id or "")
    if not agent_runs and initial_goal is not None:
        if initial_goal.status is CreatorGoalStatus.ACTIVE:
            return observed("planning")

    if final_source.failure_code is not None:
        return observed("failed", failure_code=final_source.failure_code)

    run_failed = False
    run_succeeded = False
    if latest_run is not None:
        run_failed = latest_run.status is AgentRunStatus.FAILED
        run_succeeded = latest_run.status is AgentRunStatus.SUCCEEDED
    goal_failed = False
    goal_succeeded = False
    if latest_goal is not None:
        goal_failed = latest_goal.status is CreatorGoalStatus.FAILED
        goal_succeeded = latest_goal.status is CreatorGoalStatus.COMPLETED
    session_failed = session.status is CreatorSessionStatus.ERROR
    if run_failed or goal_failed or session_failed:
        return observed("failed", failure_code="creator_runtime_failed")

    if run_succeeded or goal_succeeded:
        return observed("failed", failure_code="no_actionable_work")

    return observed("planning")


class CreatorVideoWorkflowTaskAdapter:
    """Durably bootstrap a Creator Project and its initial planning Goal."""

    submission_protocol_version = 1

    def __init__(self, services: Callable[[], CreatorFileServices]) -> None:
        self._services = services

    async def aclose(self) -> None:
        """The Creator App lifecycle owns the shared file services."""

    @staticmethod
    def action_descriptor() -> ActionDescriptor:
        return creator_create_video_action_descriptor()

    @staticmethod
    def _input_digest(normalized: CreatorVideoWorkflowInput) -> str:
        return content_digest(normalized.model_dump(mode="json"))

    @staticmethod
    def _meaning_digest(
        submission: TaskSubmission,
        normalized: CreatorVideoWorkflowInput,
        initial_goal: str,
    ) -> str:
        return content_digest(
            {
                "task_id": submission.handle.task_id,
                "submission_id": submission.handle.submission_id,
                "scope": submission.handle.scope.model_dump(mode="json"),
                "origin": submission.handle.origin.model_dump(mode="json"),
                "descriptor_digest": submission.action.descriptor_digest,
                "normalized_input": normalized.model_dump(mode="json"),
                "goal_mapping_version": CREATOR_VIDEO_GOAL_MAPPING_VERSION,
                "initial_goal": initial_goal,
            },
        )

    def _validate(
        self,
        submission: TaskSubmission,
    ) -> tuple[str, CreatorVideoWorkflowInput, str]:
        descriptor = self.action_descriptor()
        descriptor_digest = descriptor.descriptor_digest
        if (
            submission.action.descriptor_digest != descriptor_digest
            or submission.handle.action_id != _CREATE_VIDEO_ACTION_ID
            or submission.handle.descriptor_digest != descriptor_digest
        ):
            raise TaskStoreError("creator_video_workflow_action_mismatch")
        if (
            submission.handle.scope.app_id != _CREATOR_APP_ID
            or submission.handle.origin.engagement != "delegated"
        ):
            raise TaskStoreError("creator_video_workflow_scope_mismatch")
        descriptor.validate_inputs(submission.inputs)
        normalized = normalize_creator_video_workflow_input(submission.inputs)
        submission_id = require_safe_runtime_segment(
            submission.handle.submission_id,
            label="Host submission_id",
        )
        initial_goal = render_creator_video_goal_v1(
            normalized,
            submission_id,
        )
        return submission_id, normalized, initial_goal

    @staticmethod
    def _project_request(
        submission_id: str,
        normalized: CreatorVideoWorkflowInput,
        initial_goal: str,
    ) -> ProjectCreateRequest:
        payload: dict[str, Any] = {
            "clientRequestId": submission_id,
            "name": derive_creator_video_project_name(
                normalized,
                submission_id,
            ),
            "description": normalized.description,
            "scenario": normalized.scenario,
            "aspectRatio": normalized.aspect_ratio,
            "resolution": normalized.resolution,
            "initialGoal": initial_goal,
        }
        if normalized.content_type is not None:
            payload["contentType"] = normalized.content_type
        return ProjectCreateRequest.model_validate(payload)

    def _candidate(
        self,
        services: CreatorFileServices,
        submission: TaskSubmission,
    ) -> tuple[CreatorVideoWorkflowSubmission, ProjectCreateRequest]:
        submission_id, normalized, initial_goal = self._validate(submission)
        created_at = time.time()
        candidate = CreatorVideoWorkflowSubmission(
            task_id=submission.handle.task_id,
            submission_id=submission_id,
            descriptor_digest=submission.action.descriptor_digest,
            normalized_input=normalized,
            input_digest=self._input_digest(normalized),
            meaning_digest=self._meaning_digest(
                submission,
                normalized,
                initial_goal,
            ),
            goal_digest=content_digest(initial_goal),
            project_id=services.project_creation.project_id(submission_id),
            events=(
                _workflow_event(
                    "prepared",
                    0,
                    created_at=created_at,
                ),
            ),
            created_at=created_at,
            updated_at=created_at,
        )
        request = self._project_request(
            submission_id,
            normalized,
            initial_goal,
        )
        return candidate, request

    @staticmethod
    def _store(
        services: CreatorFileServices,
        submission_id: str,
    ) -> AtomicJsonRecordStore[CreatorVideoWorkflowSubmission]:
        safe_submission_id = require_safe_runtime_segment(
            submission_id,
            label="Host submission_id",
        )
        return AtomicJsonRecordStore(
            services.root
            / ".pawapp"
            / "video-workflows"
            / f"{safe_submission_id}.json",
            CreatorVideoWorkflowSubmission,
        )

    @staticmethod
    def _require_same_submission(
        current: CreatorVideoWorkflowSubmission,
        candidate: CreatorVideoWorkflowSubmission,
    ) -> None:
        if (
            current.task_id != candidate.task_id
            or current.submission_id != candidate.submission_id
            or current.descriptor_digest != candidate.descriptor_digest
            or current.normalized_input != candidate.normalized_input
            or current.input_digest != candidate.input_digest
            or current.meaning_digest != candidate.meaning_digest
            or current.goal_mapping_version != candidate.goal_mapping_version
            or current.goal_digest != candidate.goal_digest
            or current.project_id != candidate.project_id
        ):
            raise TaskStoreError("creator_video_workflow_submission_conflict")

    def _prepare(
        self,
        services: CreatorFileServices,
        submission: TaskSubmission,
    ) -> tuple[CreatorVideoWorkflowSubmission, ProjectCreateRequest]:
        candidate, request = self._candidate(services, submission)
        store = self._store(services, candidate.submission_id)
        created = store.try_create(candidate)
        current = created.value if created is not None else store.read()
        self._require_same_submission(current, candidate)
        return current, request

    def _read(
        self,
        services: CreatorFileServices,
        submission: TaskSubmission,
    ) -> tuple[
        CreatorVideoWorkflowSubmission | None,
        CreatorVideoWorkflowSubmission,
        ProjectCreateRequest,
    ]:
        candidate, request = self._candidate(services, submission)
        current = self._store(
            services,
            candidate.submission_id,
        ).read_or_none()
        if current is not None:
            self._require_same_submission(current, candidate)
        return current, candidate, request

    def _transition_bootstrapping(
        self,
        services: CreatorFileServices,
        record: CreatorVideoWorkflowSubmission,
    ) -> CreatorVideoWorkflowSubmission:
        store = self._store(services, record.submission_id)

        def update(
            current: CreatorVideoWorkflowSubmission,
        ) -> CreatorVideoWorkflowSubmission:
            self._require_same_submission(current, record)
            if current.stage != "prepared":
                return current
            now = time.time()
            event = _workflow_event(
                "bootstrapping",
                len(current.events),
                created_at=now,
            )
            return current.model_copy(
                update={
                    "stage": "bootstrapping",
                    "events": (*current.events, event),
                    "updated_at": now,
                },
            )

        return store.update(update).value

    @staticmethod
    def _require_creation_result(
        record: CreatorVideoWorkflowSubmission,
        result: ProjectCreationResult,
    ) -> None:
        response = result.response
        if (
            response.project_id != record.project_id
            or result.goal_id is None
            or result.initial_message_id is None
        ):
            raise TaskStoreError("creator_video_workflow_bootstrap_mismatch")

    def _transition_planning(
        self,
        services: CreatorFileServices,
        record: CreatorVideoWorkflowSubmission,
        result: ProjectCreationResult,
    ) -> CreatorVideoWorkflowSubmission:
        self._require_creation_result(record, result)
        response = result.response
        store = self._store(services, record.submission_id)

        def update(
            current: CreatorVideoWorkflowSubmission,
        ) -> CreatorVideoWorkflowSubmission:
            self._require_same_submission(current, record)
            identities = (
                current.creator_session_id,
                current.conversation_id,
                current.goal_id,
                current.initial_message_id,
            )
            expected = (
                response.creator_session_id,
                response.conversation_id,
                result.goal_id,
                result.initial_message_id,
            )
            if current.stage not in {"prepared", "bootstrapping"}:
                if identities != expected:
                    raise TaskStoreError(
                        "creator_video_workflow_bootstrap_mismatch",
                    )
                return current
            if current.stage == "prepared":
                raise TaskStoreError(
                    "creator_video_workflow_bootstrap_transition_missing",
                )
            now = time.time()
            event = _workflow_event(
                "planning",
                len(current.events),
                created_at=now,
            )
            return current.model_copy(
                update={
                    "creator_session_id": response.creator_session_id,
                    "conversation_id": response.conversation_id,
                    "goal_id": result.goal_id,
                    "initial_message_id": result.initial_message_id,
                    "correlated_goal_ids": (result.goal_id,),
                    "stage": "planning",
                    "events": (*current.events, event),
                    "updated_at": now,
                },
            )

        return store.update(update).value

    @staticmethod
    def _run_ref(
        record: CreatorVideoWorkflowSubmission,
    ) -> ExecutorRunRef:
        return ExecutorRunRef(
            executor_id=CREATOR_VIDEO_WORKFLOW_EXECUTOR_ID,
            session_id=record.project_id,
            run_id=record.submission_id,
        )

    @staticmethod
    def _authorization(
        services: CreatorFileServices,
        record: CreatorVideoWorkflowSubmission,
        authorization_id: str,
    ) -> ExecutionAuthorizationRecord:
        authorization = ProjectExecutionStore(
            services.root,
        ).get_execution_authorization(
            record.project_id,
            authorization_id,
        )
        correlated = (
            authorization.run_id in record.correlated_run_ids
            or authorization.round_id in record.correlated_round_ids
            or authorization.task_id in record.correlated_task_ids
            or authorization.metadata.get("parentRunId")
            in record.correlated_run_ids
        )
        if not correlated:
            raise TaskStoreError(
                "creator_video_workflow_authorization_mismatch",
            )
        return authorization

    @classmethod
    def _authorization_for_request(
        cls,
        services: CreatorFileServices,
        record: CreatorVideoWorkflowSubmission,
        request_id: str,
    ) -> ExecutionAuthorizationRecord | None:
        for event in reversed(record.events):
            authorization_id = event.approval_request_id
            if authorization_id is None:
                continue
            authorization = cls._authorization(
                services,
                record,
                authorization_id,
            )
            if _approval_request_id(record, authorization) == request_id:
                return authorization
        return None

    @staticmethod
    def _approval_target(command: TaskCommand) -> ExecutionAuthorizationStatus:
        if command.kind != "answer":
            raise TaskStoreError("creator_video_workflow_answer_required")
        answers = command.payload.get("answers")
        if not isinstance(answers, list) or len(answers) != 1:
            raise TaskStoreError("creator_video_workflow_answer_invalid")
        try:
            answer = TaskAnswer.model_validate(answers[0])
        except ValueError:
            raise TaskStoreError(
                "creator_video_workflow_answer_invalid",
            ) from None
        if (
            answer.question != _APPROVAL_QUESTION
            or answer.custom_text is not None
        ):
            raise TaskStoreError("creator_video_workflow_answer_invalid")
        if answer.selected_options == ("Approve once",):
            return ExecutionAuthorizationStatus.APPROVED
        if answer.selected_options == ("Do not run",):
            return ExecutionAuthorizationStatus.REJECTED
        raise TaskStoreError("creator_video_workflow_answer_invalid")

    @staticmethod
    def _authorization_command_state(
        authorization: ExecutionAuthorizationRecord,
        target: ExecutionAuthorizationStatus,
    ) -> CommandLookup:
        if authorization.status is target:
            return CommandLookup(state="accepted")
        if authorization.status is ExecutionAuthorizationStatus.PENDING:
            if (
                target is ExecutionAuthorizationStatus.APPROVED
                and authorization.expires_at is not None
                and utc_now() >= authorization.expires_at
            ):
                return CommandLookup(
                    state="rejected",
                    reason="approval_expired",
                )
            return CommandLookup(state="not_found")
        return CommandLookup(
            state="rejected",
            reason=(
                "approval_expired"
                if authorization.status is ExecutionAuthorizationStatus.EXPIRED
                else "approval_already_decided"
            ),
        )

    def _reconcile_bootstrap(
        self,
        services: CreatorFileServices,
        record: CreatorVideoWorkflowSubmission,
        result: ProjectCreationResult,
    ) -> CreatorVideoWorkflowSubmission:
        record = self._transition_bootstrapping(services, record)
        record = self._transition_planning(services, record, result)
        notify_creator_agent_runtime(record.project_id)
        return record

    @staticmethod
    def _observe_creator_state(
        services: CreatorFileServices,
        record: CreatorVideoWorkflowSubmission,
        executor_sequence: int | None,
    ) -> _ObservedWorkflowState:
        if (
            record.creator_session_id is None
            or record.conversation_id is None
            or record.goal_id is None
            or record.initial_message_id is None
        ):
            raise TaskStoreError("creator_video_workflow_bootstrap_incomplete")

        executions = ProjectExecutionStore(services.root)
        with services.projects.lifecycle_lock(record.project_id, shared=True):
            project = services.projects.read(record.project_id)
            all_tasks = executions.list_tasks(
                record.project_id,
                _lifecycle_lock_held=True,
            )
            graph = derive_work_graph(
                project.project,
                tasks=all_tasks,
                media_models=(get_image_model_name(), get_video_model_name()),
            )
        session = services.sessions.get_project_session_snapshot(
            record.project_id,
        )
        initial_goal = services.sessions.get_goal(
            record.project_id,
            record.goal_id,
        )
        if (
            session.project_id != record.project_id
            or session.session_id != record.creator_session_id
            or initial_goal.project_id != record.project_id
            or initial_goal.creator_session_id != record.creator_session_id
            or initial_goal.conversation_id != record.conversation_id
        ):
            raise TaskStoreError("creator_video_workflow_runtime_mismatch")

        messages = services.sessions.list_messages(
            record.project_id,
            record.creator_session_id,
            after_seq=0,
            limit=None,
        )
        initial_message = next(
            (
                message
                for message in messages
                if message.message_id == record.initial_message_id
            ),
            None,
        )
        if (
            initial_message is None
            or initial_message.conversation_id != record.conversation_id
        ):
            raise TaskStoreError("creator_video_workflow_runtime_mismatch")

        workflow_messages = tuple(
            message
            for message in messages
            if message.conversation_id == record.conversation_id
        )
        all_agent_runs = CreatorAgentRunStore(services.root).list(
            record.project_id,
        )
        all_specialist_runs = executions.list_specialist_runs(
            record.project_id,
        )

        notification_message_ids: frozenset[str] = frozenset()
        while True:
            (
                agent_runs,
                goal_ids,
                message_ids,
                message_sequences,
            ) = _correlated_agent_runs(
                record,
                all_agent_runs,
                workflow_messages,
                additional_message_ids=notification_message_ids,
            )
            agent_run_ids = frozenset(run.run_id for run in agent_runs)
            agent_round_ids = frozenset(run.round_id for run in agent_runs)
            specialist_runs = _correlated_specialist_runs(
                all_specialist_runs,
                agent_run_ids=agent_run_ids,
                round_ids=agent_round_ids,
            )
            all_run_ids = frozenset(
                (*agent_run_ids, *(run.run_id for run in specialist_runs)),
            )
            all_round_ids = frozenset(
                (*agent_round_ids, *(run.round_id for run in specialist_runs)),
            )
            tasks = _correlated_tasks(
                all_tasks,
                run_ids=all_run_ids,
                round_ids=all_round_ids,
                message_ids=message_ids,
                message_sequences=message_sequences,
            )
            linked_notification_ids = _correlated_runtime_notifications(
                workflow_messages,
                specialist_run_ids=frozenset(
                    run.run_id for run in specialist_runs
                ),
                tasks=tasks,
                graph=graph,
            )
            expanded_notification_ids = (
                notification_message_ids | linked_notification_ids
            )
            if expanded_notification_ids == notification_message_ids:
                break
            notification_message_ids = expanded_notification_ids

        goals = tuple(
            services.sessions.get_goal(record.project_id, goal_id)
            for goal_id in goal_ids
        )
        task_ids = frozenset(task.task_id for task in tasks)
        pending_authorizations = tuple(
            authorization
            for authorization in _correlated_authorizations(
                executions.list_execution_authorizations(record.project_id),
                run_ids=all_run_ids,
                round_ids=all_round_ids,
                task_ids=task_ids,
                message_ids=message_ids,
                message_sequences=message_sequences,
            )
            if authorization.status is ExecutionAuthorizationStatus.PENDING
        )
        (
            pending_authorizations,
            expired_authorization,
        ) = _expire_stale_pending_authorizations(
            executions,
            project,
            graph,
            pending_authorizations,
        )
        if expired_authorization:
            notify_creator_agent_runtime(record.project_id)
        review_ids = frozenset(
            review_id for run in agent_runs for review_id in run.review_ids
        )
        pending_reviews = _correlated_reviews(
            services.reviews.all_pending(record.project_id),
            review_ids=review_ids,
            run_ids=all_run_ids,
            round_ids=all_round_ids,
        )
        pending_resume = any(
            message.message_id in message_ids
            and message.source in _RESUME_MESSAGE_SOURCES
            and not any(
                run.caused_by_message_id == message.message_id
                or run.caused_by_message_seq == message.message_seq
                for run in agent_runs
            )
            for message in messages
        )
        return _classify_observed_state(
            record=record,
            project_snapshot=project,
            session=session,
            goals=goals,
            agent_runs=agent_runs,
            specialist_runs=specialist_runs,
            tasks=tasks,
            pending_authorizations=pending_authorizations,
            pending_reviews=pending_reviews,
            pending_resume=pending_resume,
            graph=graph,
            executor_sequence=executor_sequence,
        )

    def _transition_observed_state(
        self,
        services: CreatorFileServices,
        record: CreatorVideoWorkflowSubmission,
        observed: _ObservedWorkflowState,
    ) -> CreatorVideoWorkflowSubmission:
        store = self._store(services, record.submission_id)

        def update(
            current: CreatorVideoWorkflowSubmission,
        ) -> CreatorVideoWorkflowSubmission:
            self._require_same_submission(current, record)
            if current.stage in _TERMINAL_WORKFLOW_STAGES:
                return current
            if (
                current.creator_session_id != record.creator_session_id
                or current.conversation_id != record.conversation_id
                or current.goal_id != record.goal_id
                or current.initial_message_id != record.initial_message_id
            ):
                raise TaskStoreError(
                    "creator_video_workflow_runtime_mismatch",
                )

            stage = observed.stage
            source_receipt = current.source_receipt
            publication = current.publication
            publication_committed = current.publication_committed
            if publication is not None:
                stage = "publishing"
            elif observed.source_receipt is not None:
                source_receipt = observed.source_receipt
                publication = _publication_intent(current, source_receipt)
                publication_committed = True

            waiting_setup = stage == "waiting_setup"
            setup_request_id = None
            if waiting_setup:
                setup_request_id = current.setup_request_id
            approval_request_id = (
                observed.approval_request_id
                if stage == "waiting_approval"
                else None
            )
            failure_code = None
            if stage == "failed":
                failure_code = observed.failure_code
            current_identities = (
                current.correlated_goal_ids,
                current.correlated_run_ids,
                current.correlated_round_ids,
                current.correlated_task_ids,
            )
            observed_identities = (
                observed.correlated_goal_ids,
                observed.correlated_run_ids,
                observed.correlated_round_ids,
                observed.correlated_task_ids,
            )
            identities_changed = current_identities != observed_identities
            semantic_changed = (
                current.stage != stage
                or current.setup_request_id != setup_request_id
                or current.approval_request_id != approval_request_id
                or current.failure_code != failure_code
                or current.source_receipt != source_receipt
                or current.publication != publication
                or current.events[-1].setup_requirement_id
                != observed.setup_requirement_id
                or current.events[-1].approval_request_id
                != observed.approval_request_id
            )
            if not semantic_changed and not identities_changed:
                return current

            now = time.time()
            events = current.events
            if semantic_changed:
                next_sequence = events[-1].sequence + 1
                event_text = None
                if failure_code == "multiple_live_timelines":
                    event_text = (
                        "Creator found multiple live timelines. "
                        "Open Creator, leave one live timeline, "
                        "and start the workflow again."
                    )
                event = _workflow_event(
                    stage,
                    next_sequence,
                    evidence=observed.evidence,
                    setup_requirement_id=(
                        observed.setup_requirement_id
                        if stage == observed.stage
                        else None
                    ),
                    approval_request_id=approval_request_id,
                    text_result=event_text,
                    created_at=now,
                )
                events = (*events, event)[-_MAX_WORKFLOW_EVENTS:]
            return current.model_copy(
                update={
                    "stage": stage,
                    "setup_request_id": setup_request_id,
                    "approval_request_id": approval_request_id,
                    "correlated_goal_ids": observed.correlated_goal_ids,
                    "correlated_run_ids": observed.correlated_run_ids,
                    "correlated_round_ids": observed.correlated_round_ids,
                    "correlated_task_ids": observed.correlated_task_ids,
                    "failure_code": failure_code,
                    "publication_committed": publication_committed,
                    "source_receipt": source_receipt,
                    "publication": publication,
                    "events": events,
                    "updated_at": now,
                },
            )

        return store.update(update).value

    def _reconcile_creator_state(
        self,
        services: CreatorFileServices,
        record: CreatorVideoWorkflowSubmission,
        executor_sequence: int | None,
    ) -> CreatorVideoWorkflowSubmission:
        if record.stage in _TERMINAL_WORKFLOW_STAGES:
            return record
        observed = self._observe_creator_state(
            services,
            record,
            executor_sequence,
        )
        return self._transition_observed_state(services, record, observed)

    @staticmethod
    def _project_detail(
        record: CreatorVideoWorkflowSubmission,
        revision: int,
    ) -> dict[str, Any]:
        return {
            "project_ref": {
                "schema_version": 1,
                "app_id": _CREATOR_APP_ID,
                "project_id": record.project_id,
                "kind": "creator-project",
                "revision": max(1, revision),
            },
        }

    @staticmethod
    def _read_publication_artifact(
        services: CreatorFileServices,
        record: CreatorVideoWorkflowSubmission,
    ) -> tuple[dict[str, object], bytes]:
        source = record.source_receipt
        publication = record.publication
        if source is None or publication is None:
            raise TaskStoreError("creator_video_publication_intent_missing")
        executions = ProjectExecutionStore(services.root)
        with services.projects.lifecycle_lock(record.project_id, shared=True):
            snapshot = services.projects.read(record.project_id)
            version = snapshot.project.assets.artifact_versions_by_id.get(
                source.artifact_version_id,
            )
            indexed = snapshot.project.assets.files_by_id.get(source.file_id)
            if version is None or indexed is None:
                raise CreatorArtifactUnavailable
            task = executions.get_task(
                record.project_id,
                source.producer_task_id,
                _lifecycle_lock_held=True,
            )
            selections = version.metadata.get("sourceSelections")
            source_matches = (
                version.version_id == source.artifact_version_id
                and version.slot_id == source.slot_id
                and version.file_id == source.file_id
                and version.name == source.name
                and version.kind == "final_video"
                and not version.stale
                and version.checksum == source.sha256
                and version.owner_ref == source.owner_ref
                and version.input_fingerprint == source.render_fingerprint
                and version.metadata.get("taskId") == source.producer_task_id
                and version.metadata.get("runId") == source.producer_run_id
                and indexed.file_id == source.file_id
                and indexed.relative_uri == source.relative_uri
                and indexed.media_type == source.media_type
                and indexed.size_bytes == source.size_bytes
                and indexed.sha256 == source.sha256
                and task.status is TaskStatus.SUCCEEDED
                and task.kind is TaskKind.COMPOSE
                and task.run_id == source.producer_run_id
                and task.request_fingerprint == source.render_fingerprint
                and task.metadata.get("commandType") == "COMPOSE_FINAL_VIDEO"
                and task.metadata.get("targetRef")
                == f"timeline:{source.timeline_id}"
                and tuple(dict(item) for item in task.read_set)
                == source.read_set
                and isinstance(selections, list)
                and all(isinstance(item, Mapping) for item in selections)
                and tuple(dict(item) for item in selections)
                == source.source_selections
            )
            if not source_matches:
                raise CreatorArtifactMismatch
            artifact = read_verified_creator_artifact(
                services.projects.project_root(record.project_id),
                version=version,
                indexed=indexed,
                expected_owner_ref=source.owner_ref,
                expected_task_id=source.producer_task_id,
                source_id=publication.intent_id,
                publication_path="creator-final-video/final",
            )
        return artifact.source, artifact.content

    def _transition_publication_failed(
        self,
        services: CreatorFileServices,
        record: CreatorVideoWorkflowSubmission,
        failure_code: str,
    ) -> CreatorVideoWorkflowSubmission:
        store = self._store(services, record.submission_id)

        def update(
            current: CreatorVideoWorkflowSubmission,
        ) -> CreatorVideoWorkflowSubmission:
            self._require_same_submission(current, record)
            if current.stage in _TERMINAL_WORKFLOW_STAGES:
                return current
            if current.publication != record.publication:
                return current
            now = time.time()
            event = _workflow_event(
                "failed",
                current.events[-1].sequence + 1,
                evidence={
                    "stage": "failed",
                    "failure_code": failure_code,
                    "publication_intent_id": current.publication.intent_id,
                },
                created_at=now,
            )
            return current.model_copy(
                update={
                    "stage": "failed",
                    "failure_code": failure_code,
                    "events": (*current.events, event)[-_MAX_WORKFLOW_EVENTS:],
                    "updated_at": now,
                },
            )

        return store.update(update).value

    def _record_published_artifact(
        self,
        services: CreatorFileServices,
        record: CreatorVideoWorkflowSubmission,
        artifact_ref: ArtifactRef,
    ) -> CreatorVideoWorkflowSubmission:
        store = self._store(services, record.submission_id)

        def update(
            current: CreatorVideoWorkflowSubmission,
        ) -> CreatorVideoWorkflowSubmission:
            self._require_same_submission(current, record)
            if current.stage in _TERMINAL_WORKFLOW_STAGES:
                return current
            if current.publication != record.publication:
                return current
            publication = current.publication
            if publication is None:
                raise TaskStoreError(
                    "creator_video_publication_intent_missing",
                )
            if publication.state == "published":
                if publication.artifact_ref != artifact_ref:
                    raise TaskStoreError("creator_video_publication_conflict")
                return current
            if publication.state != "intent":
                return current
            now = time.time()
            return current.model_copy(
                update={
                    "publication": publication.model_copy(
                        update={
                            "state": "published",
                            "artifact_ref": artifact_ref,
                            "published_at": now,
                        },
                    ),
                    "updated_at": now,
                },
            )

        return store.update(update).value

    def _reconcile_publication_source(
        self,
        services: CreatorFileServices,
        record: CreatorVideoWorkflowSubmission,
    ) -> tuple[CreatorVideoWorkflowSubmission, bool]:
        store = self._store(services, record.submission_id)
        executions = ProjectExecutionStore(services.root)
        publishable = False

        def update(
            current: CreatorVideoWorkflowSubmission,
        ) -> CreatorVideoWorkflowSubmission:
            nonlocal publishable
            self._require_same_submission(current, record)
            if current.stage in _TERMINAL_WORKFLOW_STAGES:
                return current
            publication = current.publication
            source = current.source_receipt
            if publication is None or source is None:
                return current
            with services.projects.lifecycle_lock(
                current.project_id,
                shared=True,
            ):
                snapshot = services.projects.read(current.project_id)
                tasks = executions.list_tasks(
                    current.project_id,
                    _lifecycle_lock_held=True,
                )
                graph = derive_work_graph(
                    snapshot.project,
                    tasks=tasks,
                    media_models=(
                        get_image_model_name(),
                        get_video_model_name(),
                    ),
                )
                resolved = _resolve_final_source(snapshot, graph, tasks)

            now = time.time()
            if resolved.source_receipt is not None:
                latest_source = resolved.source_receipt
                if latest_source.canonical_digest == source.canonical_digest:
                    if publication.state == "intent":
                        publishable = True
                        return current
                    if publication.state != "published":
                        return current
                    artifact_ref = publication.artifact_ref
                    if artifact_ref is None:
                        raise TaskStoreError(
                            "creator_video_publication_artifact_missing",
                        )
                    generation = snapshot.generation
                    validated = publication.model_copy(
                        update={
                            "validated_project_generation": generation,
                            "validated_project_etag": snapshot.etag,
                        },
                    )
                    event = _workflow_event(
                        "succeeded",
                        current.events[-1].sequence + 1,
                        evidence={
                            "stage": "succeeded",
                            "source_receipt_digest": source.receipt_digest,
                            "publication_intent_id": publication.intent_id,
                            "artifact_id": artifact_ref.artifact_id,
                            "artifact_version": artifact_ref.version,
                            "project_generation": generation,
                            "project_etag": snapshot.etag,
                        },
                        created_at=now,
                    )
                    return current.model_copy(
                        update={
                            "stage": "succeeded",
                            "publication": validated,
                            "events": (*current.events, event)[
                                -_MAX_WORKFLOW_EVENTS:
                            ],
                            "updated_at": now,
                        },
                    )

                superseded = publication.model_copy(
                    update={
                        "state": "superseded",
                        "superseded_at": now,
                        "superseded_reason": "canonical_source_changed",
                    },
                )
                next_publication = _publication_intent(current, latest_source)
                event = _workflow_event(
                    "publishing",
                    current.events[-1].sequence + 1,
                    evidence={
                        "stage": "publishing",
                        "source_receipt_digest": latest_source.receipt_digest,
                        "superseded_intent_id": publication.intent_id,
                        "publication_intent_id": next_publication.intent_id,
                    },
                    created_at=now,
                )
                return current.model_copy(
                    update={
                        "source_receipt": latest_source,
                        "publication": next_publication,
                        "superseded_publications": (
                            *current.superseded_publications,
                            superseded,
                        )[-32:],
                        "events": (*current.events, event)[
                            -_MAX_WORKFLOW_EVENTS:
                        ],
                        "updated_at": now,
                    },
                )

            if resolved.failure_code is None:
                return current
            event_text = None
            if resolved.failure_code == "multiple_live_timelines":
                event_text = (
                    "Creator found multiple live timelines. Open Creator, "
                    "leave one live timeline, and start the workflow again."
                )
            event = _workflow_event(
                "failed",
                current.events[-1].sequence + 1,
                evidence={
                    "stage": "failed",
                    "failure_code": resolved.failure_code,
                    "publication_intent_id": publication.intent_id,
                    "project_generation": snapshot.generation,
                    "project_etag": snapshot.etag,
                },
                text_result=event_text,
                created_at=now,
            )
            return current.model_copy(
                update={
                    "stage": "failed",
                    "failure_code": resolved.failure_code,
                    "events": (*current.events, event)[-_MAX_WORKFLOW_EVENTS:],
                    "updated_at": now,
                },
            )

        return store.update(update).value, publishable

    def _finalize_published_artifact(
        self,
        services: CreatorFileServices,
        record: CreatorVideoWorkflowSubmission,
    ) -> CreatorVideoWorkflowSubmission:
        return self._reconcile_publication_source(services, record)[0]

    async def _materialize_publication(
        self,
        services: CreatorFileServices,
        submission: TaskSubmission,
        record: CreatorVideoWorkflowSubmission,
        artifacts: Any,
    ) -> CreatorVideoWorkflowSubmission:
        record, publishable = await asyncio.to_thread(
            self._reconcile_publication_source,
            services,
            record,
        )
        if record.stage in _TERMINAL_WORKFLOW_STAGES:
            return record
        publication = record.publication
        if (
            publication is None
            or publication.state != "intent"
            or not publishable
        ):
            return record
        try:
            source, content = await asyncio.to_thread(
                self._read_publication_artifact,
                services,
                record,
            )
        except (CreatorArtifactMismatch, CreatorArtifactUnavailable) as error:
            latest, still_publishable = await asyncio.to_thread(
                self._reconcile_publication_source,
                services,
                record,
            )
            if (
                latest.stage in _TERMINAL_WORKFLOW_STAGES
                or latest.publication != publication
                or not still_publishable
            ):
                return latest
            failure_code = (
                "publication_source_mismatch"
                if isinstance(error, CreatorArtifactMismatch)
                else "publication_source_unavailable"
            )
            return await asyncio.to_thread(
                self._transition_publication_failed,
                services,
                latest,
                failure_code,
            )
        source = {
            **source,
            "presentation": {
                "schema_version": 1,
                "role": "primary",
                "kind": "creator/video",
                "visibility": "chat",
                "preview": "inline",
                "rank": 0,
            },
        }
        try:
            artifact_ref = await artifacts.publish(
                submission,
                source,
                content,
            )
        except TaskStoreError:
            return await asyncio.to_thread(
                self._transition_publication_failed,
                services,
                record,
                "publication_failed",
            )
        record = await asyncio.to_thread(
            self._record_published_artifact,
            services,
            record,
            artifact_ref,
        )
        return await asyncio.to_thread(
            self._finalize_published_artifact,
            services,
            record,
        )

    async def readiness(self, scope: TaskScope, inputs: dict) -> Readiness:
        if scope.app_id != _CREATOR_APP_ID:
            return Readiness(
                state="blocked",
                reason="creator_video_workflow_scope_mismatch",
            )
        try:
            self.action_descriptor().validate_inputs(inputs)
            normalize_creator_video_workflow_input(inputs)
            self._services()
        except Exception:  # noqa: BLE001
            return Readiness(
                state="blocked",
                reason="creator_video_workflow_unavailable",
            )
        return Readiness(state="ready")

    async def submit(self, submission: TaskSubmission) -> ExecutorRunRef:
        services = self._services()
        record, request = await asyncio.to_thread(
            self._prepare,
            services,
            submission,
        )
        if record.stage not in {"prepared", "bootstrapping"}:
            if record.stage == "planning":
                notify_creator_agent_runtime(record.project_id)
            return self._run_ref(record)
        record = await asyncio.to_thread(
            self._transition_bootstrapping,
            services,
            record,
        )
        if record.stage != "bootstrapping":
            notify_creator_agent_runtime(record.project_id)
            return self._run_ref(record)
        result = await asyncio.to_thread(
            services.project_creation.create_with_runtime_identity,
            request,
        )
        record = await asyncio.to_thread(
            self._transition_planning,
            services,
            record,
            result,
        )
        notify_creator_agent_runtime(record.project_id)
        return self._run_ref(record)

    async def query(self, submission: TaskSubmission) -> SubmissionLookup:
        services = self._services()
        record, candidate, request = await asyncio.to_thread(
            self._read,
            services,
            submission,
        )
        if record is not None and record.stage not in {
            "prepared",
            "bootstrapping",
        }:
            if record.stage == "planning":
                notify_creator_agent_runtime(record.project_id)
            record = await asyncio.to_thread(
                self._reconcile_creator_state,
                services,
                record,
                submission.handle.executor_sequence,
            )
            if record.stage == "publishing":
                record = await asyncio.to_thread(
                    self._finalize_published_artifact,
                    services,
                    record,
                )
            return SubmissionLookup(
                state="accepted",
                run_ref=self._run_ref(record),
            )

        result = await asyncio.to_thread(
            services.project_creation.lookup_with_runtime_identity,
            request,
        )
        if result is None:
            return SubmissionLookup(
                state="not_found" if record is None else "unknown",
            )
        if record is None:
            store = self._store(services, candidate.submission_id)
            created = await asyncio.to_thread(store.try_create, candidate)
            record = (
                created.value
                if created is not None
                else await asyncio.to_thread(
                    store.read,
                )
            )
            self._require_same_submission(record, candidate)
        record = await asyncio.to_thread(
            self._reconcile_bootstrap,
            services,
            record,
            result,
        )
        return SubmissionLookup(
            state="accepted",
            run_ref=self._run_ref(record),
        )

    async def attach(self, submission: TaskSubmission):
        services = self._services()
        record, _candidate, _request = await asyncio.to_thread(
            self._read,
            services,
            submission,
        )
        if record is None:
            raise TaskStoreError("creator_video_workflow_submission_unknown")
        if record.stage not in {"prepared", "bootstrapping"}:
            record = await asyncio.to_thread(
                self._reconcile_creator_state,
                services,
                record,
                submission.handle.executor_sequence,
            )
            if record.stage == "publishing":
                record = await asyncio.to_thread(
                    self._finalize_published_artifact,
                    services,
                    record,
                )
        run_ref = self._run_ref(record)
        after = submission.handle.executor_sequence
        after = -1 if after is None else after
        while True:
            revision = 1
            if record.publication is not None:
                source_receipt = record.source_receipt
                if source_receipt is None:
                    raise TaskStoreError(
                        "creator_video_publication_source_missing",
                    )
                revision = (
                    record.publication.validated_project_generation
                    or source_receipt.project_generation
                )
            elif record.creator_session_id is not None:
                snapshot = await asyncio.to_thread(
                    services.projects.read,
                    record.project_id,
                )
                revision = snapshot.generation
            detail = (
                self._project_detail(record, revision)
                if record.creator_session_id is not None
                else {}
            )
            for workflow_event in record.events:
                if workflow_event.sequence <= after:
                    continue
                setup_need = None
                status = workflow_event.status
                event_detail = dict(detail)
                if workflow_event.setup_requirement_id is not None:
                    reason_code, reason = _SETUP_NEED[
                        workflow_event.setup_requirement_id
                    ]
                    status = "waiting_for_setup"
                    setup_need = TaskSetupNeed(
                        requirement_id=workflow_event.setup_requirement_id,
                        reason_code=reason_code,
                        reason=reason,
                    )
                if workflow_event.approval_request_id is not None:
                    authorization = await asyncio.to_thread(
                        self._authorization,
                        services,
                        record,
                        workflow_event.approval_request_id,
                    )
                    event_detail["input_request"] = _approval_input_request(
                        record,
                        authorization,
                    ).model_dump(mode="json")
                if submission.handle.experience is not None:
                    event_detail[
                        "experience_update"
                    ] = _creator_experience_update(
                        submission,
                        record,
                        workflow_event,
                    ).model_dump(
                        mode="json"
                    )
                yield ExecutorEvent(
                    run_ref=run_ref,
                    sequence=workflow_event.sequence,
                    cursor=workflow_event.cursor,
                    status=status,
                    text_result=workflow_event.text_result,
                    setup_need=setup_need,
                    detail=event_detail,
                )
                after = workflow_event.sequence
            if record.stage in _TERMINAL_WORKFLOW_STAGES:
                return
            latest = await asyncio.to_thread(
                self._store(services, record.submission_id).read,
            )
            if latest.events[-1].sequence <= after:
                return
            record = latest

    async def materialize_event(
        self,
        submission: TaskSubmission,
        event: ExecutorEvent,
        artifacts: Any,
    ) -> ExecutorEvent:
        services = self._services()
        record, _candidate, _request = await asyncio.to_thread(
            self._read,
            services,
            submission,
        )
        if record is None:
            raise TaskStoreError("creator_video_workflow_submission_unknown")
        matching_event = next(
            (
                item
                for item in record.events
                if item.sequence == event.sequence
                and item.cursor == event.cursor
            ),
            None,
        )
        if (
            matching_event is not None
            and matching_event.stage == "publishing"
            and matching_event == record.events[-1]
        ):
            record = await self._materialize_publication(
                services,
                submission,
                record,
                artifacts,
            )
        if matching_event is None or matching_event.stage != "succeeded":
            return event
        publication = record.publication
        if (
            record.stage != "succeeded"
            or publication is None
            or publication.state != "published"
            or publication.artifact_ref is None
            or publication.validated_project_generation is None
        ):
            raise TaskStoreError("creator_video_publication_incomplete")
        detail = dict(event.detail)
        detail.update(
            self._project_detail(
                record,
                publication.validated_project_generation,
            ),
        )
        detail["artifact_ref"] = publication.artifact_ref.model_dump(
            mode="json",
        )
        return event.model_copy(update={"detail": detail})

    @staticmethod
    def _cancel_correlated_work(
        services: CreatorFileServices,
        record: CreatorVideoWorkflowSubmission,
    ) -> None:
        executions = ProjectExecutionStore(services.root)
        correlated_run_ids = frozenset(record.correlated_run_ids)
        correlated_round_ids = frozenset(record.correlated_round_ids)
        correlated_task_ids = frozenset(record.correlated_task_ids)
        cancellation = {
            "code": "HOST_CANCELLED",
            "message": "Host task cancelled this workflow.",
        }

        for authorization in executions.list_execution_authorizations(
            record.project_id,
        ):
            correlated = (
                authorization.authorization_id == record.approval_request_id
                or authorization.run_id in correlated_run_ids
                or authorization.round_id in correlated_round_ids
                or authorization.task_id in correlated_task_ids
                or authorization.metadata.get("parentRunId")
                in correlated_run_ids
            )
            if (
                not correlated
                or authorization.status
                is not ExecutionAuthorizationStatus.PENDING
            ):
                continue
            try:
                executions.decide_execution_authorization(
                    record.project_id,
                    authorization.authorization_id,
                    authorization_token=authorization.authorization_token,
                    status=ExecutionAuthorizationStatus.EXPIRED,
                    metadata={"cancelledBy": "pawapp_task"},
                )
            except ExecutionStateConflict:
                pass

        for task in executions.list_tasks(record.project_id):
            if (
                task.task_id not in correlated_task_ids
                or task.status not in _ACTIVE_TASK_STATUSES
            ):
                continue
            try:
                executions.transition_task(
                    record.project_id,
                    task.task_id,
                    expected_status=task.status,
                    status=TaskStatus.CANCELLED,
                    updates={"error": cancellation},
                )
            except ExecutionStateConflict:
                pass

        for specialist in executions.list_specialist_runs(record.project_id):
            if (
                specialist.run_id not in correlated_run_ids
                or specialist.status in TERMINAL_SPECIALIST_STATUSES
            ):
                continue
            try:
                executions.transition_specialist_run(
                    record.project_id,
                    specialist.run_id,
                    expected_status=specialist.status,
                    status=SpecialistRunStatus.CANCELLED,
                    updates={
                        "final_marker": "CANCELLED",
                        "final_summary_text": cancellation["message"],
                    },
                )
            except ExecutionStateConflict:
                pass

        agent_runs = [
            run
            for run in CreatorAgentRunStore(services.root).list(
                record.project_id,
            )
            if run.run_id in correlated_run_ids
        ]
        for run in agent_runs:
            if run.status not in {
                AgentRunStatus.QUEUED,
                AgentRunStatus.RUNNING,
            }:
                continue
            try:
                CreatorAgentRunStore(services.root).transition(
                    record.project_id,
                    run.run_id,
                    expected_status=run.status,
                    status=AgentRunStatus.CANCELLED,
                    updates={"error": cancellation},
                )
            except AgentRunStateConflict:
                pass

        correlated_goal_ids = set(record.correlated_goal_ids)
        if record.goal_id is not None:
            correlated_goal_ids.add(record.goal_id)
        for goal_id in correlated_goal_ids:
            goal = services.sessions.get_goal(record.project_id, goal_id)
            if goal.status in {
                CreatorGoalStatus.COMPLETED,
                CreatorGoalStatus.CANCELLED,
                CreatorGoalStatus.FAILED,
            }:
                continue
            try:
                services.sessions.set_goal_status(
                    record.project_id,
                    goal_id,
                    CreatorGoalStatus.CANCELLED,
                    expected_status=goal.status,
                )
            except SessionStateConflict:
                pass

        session = services.sessions.get_project_session_snapshot(
            record.project_id,
        )
        active_run = next(
            (run for run in agent_runs if run.run_id == session.active_run_id),
            None,
        )
        if active_run is None:
            return
        try:
            services.sessions.mark_messages_consumed(
                record.project_id,
                session.session_id,
                through_seq=active_run.caused_by_message_seq,
                goal_id=active_run.goal_id,
            )
            services.sessions.clear_active_run(
                record.project_id,
                session.session_id,
                expected_run_id=active_run.run_id,
                status=CreatorSessionStatus.CANCELLED,
            )
        except SessionStateConflict:
            pass

    def _cancel_workflow(
        self,
        services: CreatorFileServices,
        record: CreatorVideoWorkflowSubmission,
    ) -> tuple[CommandLookup, CreatorVideoWorkflowSubmission]:
        store = self._store(services, record.submission_id)
        outcome = "accepted"
        reason = None

        def update(
            current: CreatorVideoWorkflowSubmission,
        ) -> CreatorVideoWorkflowSubmission:
            nonlocal outcome, reason
            self._require_same_submission(current, record)
            if current.publication_committed:
                outcome = "rejected"
                reason = "publication_committed"
                return current
            if current.stage == "cancelled":
                return current
            if current.stage in _TERMINAL_WORKFLOW_STAGES:
                outcome = "rejected"
                reason = "task_terminal"
                return current
            now = time.time()
            event = _workflow_event(
                "cancelled",
                current.events[-1].sequence + 1,
                evidence={"stage": "cancelled", "source": "host_command"},
                created_at=now,
            )
            return current.model_copy(
                update={
                    "stage": "cancelled",
                    "setup_request_id": None,
                    "approval_request_id": None,
                    "failure_code": None,
                    "events": (*current.events, event)[-_MAX_WORKFLOW_EVENTS:],
                    "updated_at": now,
                },
            )

        updated = store.update(update).value
        if outcome == "accepted":
            self._cancel_correlated_work(services, updated)
        return CommandLookup(state=outcome, reason=reason), updated

    def _apply_approval_command(
        self,
        services: CreatorFileServices,
        record: CreatorVideoWorkflowSubmission,
        request_id: str,
        target: ExecutionAuthorizationStatus,
    ) -> CommandLookup:
        store = self._store(services, record.submission_id)
        result = CommandLookup(state="not_found")
        notify = False

        def update(
            current: CreatorVideoWorkflowSubmission,
        ) -> CreatorVideoWorkflowSubmission:
            nonlocal result, notify
            self._require_same_submission(current, record)
            authorization = self._authorization_for_request(
                services,
                current,
                request_id,
            )
            if authorization is None:
                result = CommandLookup(
                    state="rejected",
                    reason="stale_request",
                )
                return current
            command_state = self._authorization_command_state(
                authorization,
                target,
            )
            if command_state.state != "not_found":
                result = command_state
                return current
            if (
                current.stage != "waiting_approval"
                or current.approval_request_id
                != authorization.authorization_id
            ):
                result = CommandLookup(
                    state="rejected",
                    reason="stale_request",
                )
                return current
            decision = None
            if target is ExecutionAuthorizationStatus.APPROVED:
                decision = {
                    "provider": authorization.requested_provider,
                    "model": authorization.requested_model,
                    "maxCost": 0,
                    "maxCandidates": (authorization.requested_candidates or 1),
                }
            decide_execution_authorization(
                ProjectExecutionStore(services.root),
                current.project_id,
                authorization.authorization_id,
                authorization_token=authorization.authorization_token,
                target_status=target,
                decision=decision,
            )
            result = CommandLookup(state="accepted")
            notify = True
            return current

        store.update(update)
        if notify:
            notify_creator_agent_runtime(record.project_id)
        return result

    async def command(
        self,
        submission: TaskSubmission,
        command: TaskCommand,
    ) -> CommandLookup:
        if command.task_id != submission.handle.task_id:
            raise TaskStoreError(
                "creator_video_workflow_command_task_mismatch",
            )
        services = self._services()
        record, _candidate, _request = await asyncio.to_thread(
            self._read,
            services,
            submission,
        )
        if record is None:
            return CommandLookup(state="not_found")
        if command.kind == "cancel":
            result, cancelled_record = await asyncio.to_thread(
                self._cancel_workflow,
                services,
                record,
            )
            if result.state == "accepted":
                await cancel_correlated_creator_agent_runtime(
                    cancelled_record.project_id,
                    agent_run_ids=cancelled_record.correlated_run_ids,
                    specialist_run_ids=cancelled_record.correlated_run_ids,
                )
            return result
        if command.request_id is None:
            return CommandLookup(
                state="rejected",
                reason="invalid_task_answer",
            )
        try:
            target = self._approval_target(command)
        except TaskStoreError:
            return CommandLookup(
                state="rejected",
                reason="invalid_task_answer",
            )
        return await asyncio.to_thread(
            self._apply_approval_command,
            services,
            record,
            command.request_id,
            target,
        )

    async def query_command(
        self,
        submission: TaskSubmission,
        command: TaskCommand,
    ) -> CommandLookup:
        if command.task_id != submission.handle.task_id:
            raise TaskStoreError(
                "creator_video_workflow_command_task_mismatch",
            )
        services = self._services()
        record, _candidate, _request = await asyncio.to_thread(
            self._read,
            services,
            submission,
        )
        if record is None:
            return CommandLookup(state="not_found")
        if command.kind == "cancel":
            if record.publication_committed:
                return CommandLookup(
                    state="rejected",
                    reason="publication_committed",
                )
            if record.stage == "cancelled":
                return CommandLookup(state="accepted")
            if record.stage in _TERMINAL_WORKFLOW_STAGES:
                return CommandLookup(state="rejected", reason="task_terminal")
            return CommandLookup(state="not_found")
        if command.request_id is None:
            return CommandLookup(
                state="rejected",
                reason="command_unsupported",
            )
        try:
            target = self._approval_target(command)
        except TaskStoreError:
            return CommandLookup(
                state="rejected",
                reason="invalid_task_answer",
            )
        authorization = await asyncio.to_thread(
            self._authorization_for_request,
            services,
            record,
            command.request_id,
        )
        if authorization is None:
            return CommandLookup(state="rejected", reason="stale_request")
        current = self._authorization_command_state(authorization, target)
        if current.state != "not_found":
            return current
        if (
            record.stage != "waiting_approval"
            or record.approval_request_id != authorization.authorization_id
        ):
            return CommandLookup(state="rejected", reason="stale_request")
        return current


__all__ = [
    "CREATOR_VIDEO_GOAL_MAPPING_VERSION",
    "CREATOR_VIDEO_WORKFLOW_EXECUTOR_ID",
    "CreatorVideoWorkflowEvent",
    "CreatorVideoWorkflowInput",
    "CreatorVideoWorkflowStage",
    "CreatorVideoWorkflowSubmission",
    "CreatorVideoWorkflowTaskAdapter",
    "creator_create_video_action_descriptor",
    "creator_video_goal_digest_v1",
    "derive_creator_video_project_name",
    "normalize_creator_video_workflow_input",
    "render_creator_video_goal_v1",
]
