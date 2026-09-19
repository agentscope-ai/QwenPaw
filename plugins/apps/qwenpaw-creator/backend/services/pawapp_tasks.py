# -*- coding: utf-8 -*-
"""Protocol-1 Host task adapters for Creator's durable media runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from pydantic import Field

from domain.enums import CreatorCommandType, TaskKind, TaskStatus
from domain.errors import (
    CreatorError,
    ValidationError as CreatorValidationError,
)
from schemas.projects import ProjectCreateRequest
from services.media_files.image_execution import (
    FileImageDispatch,
    dispatch_file_image_command,
    file_image_execution_service,
)
from services.media_files.r2v_execution import (
    FileR2VDispatch,
    execute_file_r2v_command,
    file_r2v_execution_service,
)
from services.pawapp_artifacts import (
    CreatorArtifactMismatch,
    CreatorArtifactUnavailable,
    read_verified_creator_artifact,
)
from services.project_files.facade import CreatorFileServices
from services.runtime_files.atomic_store import AtomicJsonRecordStore
from services.runtime_files.errors import RecordNotFoundError
from services.runtime_files.execution_models import (
    TaskAttemptEvent,
    TaskRecord,
)
from services.runtime_files.execution_store import ProjectExecutionStore
from services.runtime_files.models import StrictRuntimeModel, utc_now
from services.runtime_files.path_safety import require_safe_runtime_segment

from qwenpaw.pawapp.tasks import (
    ActionDescriptor,
    CommandLookup,
    ExecutorEvent,
    ExecutorRunRef,
    SubmissionLookup,
    TaskCommand,
    TaskScope,
    TaskStoreError,
    TaskSubmission,
)
from qwenpaw.pawapp.tasks.binding import Readiness
from qwenpaw.pawapp.tasks.contracts import content_digest

APP_ID = "qwenpaw-creator"
CREATE_PROJECT_ACTION_ID = "create-project"
VIDEO_ACTION_ID = "generate-video"
STORYBOARD_ACTION_ID = "generate-storyboard"
CREATE_PROJECT_EXECUTOR_ID = "qwenpaw-creator.project-creation"
VIDEO_EXECUTOR_ID = "qwenpaw-creator.video"
STORYBOARD_EXECUTOR_ID = "qwenpaw-creator.storyboard"
_ARTIFACT_VERSION_DETAIL = "creator_artifact_version_id"
# Backward-compatible module names for the first shipped action.
ACTION_ID = VIDEO_ACTION_ID
EXECUTOR_ID = VIDEO_EXECUTOR_ID
_TERMINAL = {
    TaskStatus.SUCCEEDED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.QUARANTINED,
}


def creator_create_project_action_descriptor() -> ActionDescriptor:
    return ActionDescriptor(
        app_id=APP_ID,
        action_id=CREATE_PROJECT_ACTION_ID,
        summary=(
            "Create a new empty Creator project and return a reference "
            "that can be opened in Creator."
        ),
        engagements=("delegated",),
        input_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "minLength": 1,
                    "pattern": r"\S",
                },
                "description": {"type": "string", "default": ""},
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
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        output_types=("text/plain",),
        permissions=("creator.project.create",),
        effects=("project_mutation",),
        adapter_ref="qwenpaw-creator.project-creation.v1",
    )


def creator_video_action_descriptor() -> ActionDescriptor:
    """Describe generation from one committed storyboard-backed element."""
    return ActionDescriptor(
        app_id=APP_ID,
        action_id=VIDEO_ACTION_ID,
        summary=(
            "Generate video for one existing Creator project element using "
            "its committed prompt, storyboard, references, and settings."
        ),
        engagements=("delegated", "direct"),
        input_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$",
                },
                "target_ref": {
                    "type": "string",
                    "pattern": (
                        r"^element:[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$"
                    ),
                },
            },
            "required": ["project_id", "target_ref"],
            "additionalProperties": False,
        },
        output_types=("text/plain", "qwenpaw:file"),
        permissions=(
            "creator.project.read",
            "creator.project.write",
            "creator.video.generate",
        ),
        effects=("model_usage", "project_mutation"),
        adapter_ref="qwenpaw-creator.video-generation.v1",
    )


def creator_storyboard_action_descriptor() -> ActionDescriptor:
    """Describe storyboard generation for one committed project element."""
    return ActionDescriptor(
        app_id=APP_ID,
        action_id=STORYBOARD_ACTION_ID,
        summary=(
            "Generate a storyboard image for one existing Creator project "
            "element using its committed prompt, visual design, references, "
            "and settings."
        ),
        engagements=("delegated", "direct"),
        input_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$",
                },
                "target_ref": {
                    "type": "string",
                    "pattern": (
                        r"^element:[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$"
                    ),
                },
            },
            "required": ["project_id", "target_ref"],
            "additionalProperties": False,
        },
        output_types=("text/plain", "qwenpaw:file"),
        permissions=(
            "creator.project.read",
            "creator.project.write",
            "creator.image.generate",
        ),
        effects=("model_usage", "project_mutation"),
        adapter_ref="qwenpaw-creator.storyboard-generation.v1",
    )


class CreatorProjectCreationSubmission(StrictRuntimeModel):
    schema_version: Literal[1] = 1
    submission_id: str = Field(min_length=1, max_length=192)
    meaning_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_id: str = Field(min_length=1, max_length=192)
    state: Literal["prepared", "accepted", "failed"] = "prepared"
    failure_code: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CreatorCreateProjectTaskAdapter:
    submission_protocol_version = 1

    def __init__(self, services: Callable[[], CreatorFileServices]) -> None:
        self._services = services

    async def aclose(self) -> None:
        pass

    @staticmethod
    def action_descriptor() -> ActionDescriptor:
        return creator_create_project_action_descriptor()

    @staticmethod
    def _meaning(submission: TaskSubmission) -> str:
        return content_digest(
            {
                "task_id": submission.handle.task_id,
                "scope": submission.handle.scope.model_dump(mode="json"),
                "origin": submission.handle.origin.model_dump(mode="json"),
                "action": submission.action.descriptor_digest,
                "inputs": submission.inputs,
            },
        )

    def _validate(
        self,
        submission: TaskSubmission,
    ) -> tuple[str, ProjectCreateRequest]:
        descriptor = self.action_descriptor()
        if (
            submission.action.descriptor_digest != descriptor.descriptor_digest
            or submission.handle.action_id != CREATE_PROJECT_ACTION_ID
            or submission.handle.descriptor_digest
            != descriptor.descriptor_digest
        ):
            raise TaskStoreError("creator_create_project_action_mismatch")
        descriptor.validate_inputs(submission.inputs)
        if submission.handle.scope.app_id != APP_ID:
            raise TaskStoreError("creator_create_project_scope_mismatch")
        submission_id = require_safe_runtime_segment(
            submission.handle.submission_id,
            label="Host submission_id",
        )
        inputs = submission.inputs
        payload = {
            "clientRequestId": submission_id,
            "name": inputs["name"],
            "description": inputs.get("description", ""),
            "scenario": inputs.get("scenario", "general"),
            "aspectRatio": inputs.get("aspect_ratio", "16:9"),
            "resolution": inputs.get("resolution", "720P"),
        }
        if "content_type" in inputs:
            payload["contentType"] = inputs["content_type"]
        return submission_id, ProjectCreateRequest.model_validate(payload)

    @staticmethod
    def _store(
        services: CreatorFileServices,
        submission_id: str,
    ) -> AtomicJsonRecordStore[CreatorProjectCreationSubmission]:
        return AtomicJsonRecordStore(
            services.root
            / ".pawapp"
            / "create-project-submissions"
            / f"{submission_id}.json",
            CreatorProjectCreationSubmission,
        )

    def _candidate(
        self,
        services: CreatorFileServices,
        submission: TaskSubmission,
    ) -> tuple[CreatorProjectCreationSubmission, ProjectCreateRequest]:
        submission_id, request = self._validate(submission)
        return (
            CreatorProjectCreationSubmission(
                submission_id=submission_id,
                meaning_digest=self._meaning(submission),
                project_id=services.project_creation.project_id(submission_id),
            ),
            request,
        )

    def _prepare(
        self,
        services: CreatorFileServices,
        submission: TaskSubmission,
    ) -> tuple[CreatorProjectCreationSubmission, ProjectCreateRequest]:
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
    ) -> tuple[CreatorProjectCreationSubmission | None, ProjectCreateRequest]:
        candidate, request = self._candidate(services, submission)
        current = self._store(
            services,
            candidate.submission_id,
        ).read_or_none()
        if current is not None:
            self._require_same_submission(current, candidate)
        return current, request

    @staticmethod
    def _require_same_submission(
        current: CreatorProjectCreationSubmission,
        candidate: CreatorProjectCreationSubmission,
    ) -> None:
        if (
            current.submission_id != candidate.submission_id
            or current.meaning_digest != candidate.meaning_digest
            or current.project_id != candidate.project_id
        ):
            raise TaskStoreError("creator_create_project_submission_conflict")

    def _transition(
        self,
        services: CreatorFileServices,
        record: CreatorProjectCreationSubmission,
        *,
        state: Literal["accepted", "failed"],
        failure_code: str | None = None,
    ) -> CreatorProjectCreationSubmission:
        store = self._store(services, record.submission_id)

        def update(current: CreatorProjectCreationSubmission):
            self._require_same_submission(current, record)
            if current.state != "prepared":
                if (
                    current.state == state
                    and current.failure_code == failure_code
                ):
                    return current
                raise TaskStoreError(
                    "creator_create_project_submission_conflict",
                )
            return current.model_copy(
                update={
                    "state": state,
                    "failure_code": failure_code,
                    "updated_at": utc_now(),
                },
            )

        return store.update(update).value

    @staticmethod
    def _run_ref(
        record: CreatorProjectCreationSubmission,
    ) -> ExecutorRunRef:
        return ExecutorRunRef(
            executor_id=CREATE_PROJECT_EXECUTOR_ID,
            session_id=record.project_id,
            run_id=record.submission_id,
        )

    def _reconcile(
        self,
        services: CreatorFileServices,
        record: CreatorProjectCreationSubmission,
        request: ProjectCreateRequest,
    ) -> CreatorProjectCreationSubmission | None:
        response = services.project_creation.lookup(request)
        if response is None:
            return None
        if response.project_id != record.project_id:
            raise TaskStoreError("creator_create_project_project_mismatch")
        if record.state == "prepared":
            return self._transition(services, record, state="accepted")
        if record.state != "accepted":
            raise TaskStoreError("creator_create_project_submission_conflict")
        return record

    async def readiness(self, scope: TaskScope, inputs: dict) -> Readiness:
        if scope.app_id != APP_ID:
            return Readiness(
                state="blocked",
                reason="creator_create_project_scope_mismatch",
            )
        try:
            self.action_descriptor().validate_inputs(inputs)
            self._services()
        except Exception:  # noqa: BLE001
            return Readiness(
                state="blocked",
                reason="creator_project_unavailable",
            )
        return Readiness(state="ready")

    async def submit(self, submission: TaskSubmission) -> ExecutorRunRef:
        services = self._services()
        record, request = await asyncio.to_thread(
            self._prepare,
            services,
            submission,
        )
        if record.state in {"accepted", "failed"}:
            return self._run_ref(record)
        try:
            response = await asyncio.to_thread(
                services.project_creation.create,
                request,
            )
        except CreatorValidationError as error:
            record = await asyncio.to_thread(
                self._transition,
                services,
                record,
                state="failed",
                failure_code=str(error.code).casefold(),
            )
            return self._run_ref(record)
        if response.project_id != record.project_id:
            raise TaskStoreError("creator_create_project_project_mismatch")
        record = await asyncio.to_thread(
            self._transition,
            services,
            record,
            state="accepted",
        )
        return self._run_ref(record)

    async def query(self, submission: TaskSubmission) -> SubmissionLookup:
        services = self._services()
        record, request = await asyncio.to_thread(
            self._read,
            services,
            submission,
        )
        if record is None:
            candidate, _ = self._candidate(services, submission)
            response = await asyncio.to_thread(
                services.project_creation.lookup,
                request,
            )
            if response is None:
                return SubmissionLookup(state="not_found")
            if response.project_id != candidate.project_id:
                raise TaskStoreError("creator_create_project_project_mismatch")
            record, _ = await asyncio.to_thread(
                self._prepare,
                services,
                submission,
            )
        if record.state == "prepared":
            reconciled = await asyncio.to_thread(
                self._reconcile,
                services,
                record,
                request,
            )
            if reconciled is None:
                return SubmissionLookup(state="not_found")
            record = reconciled
        return SubmissionLookup(
            state="accepted",
            run_ref=self._run_ref(record),
        )

    async def attach(self, submission: TaskSubmission):
        services = self._services()
        record, _ = await asyncio.to_thread(
            self._read,
            services,
            submission,
        )
        if record is None or record.state == "prepared":
            raise TaskStoreError("creator_create_project_submission_unknown")
        run_ref = self._run_ref(record)
        after = submission.handle.executor_sequence
        after = -1 if after is None else after
        if record.state == "failed":
            if after < 0:
                yield ExecutorEvent(
                    run_ref=run_ref,
                    sequence=0,
                    cursor="creator-create-project-failed",
                    status="failed",
                    text_result="Creator could not create the project.",
                    detail={
                        "reason_code": record.failure_code or "creator_error",
                    },
                )
            return
        if after < 0:
            yield ExecutorEvent(
                run_ref=run_ref,
                sequence=0,
                cursor="creator-create-project-running",
                status="running",
                text_result="Creator is creating the project.",
            )
        if after < 1:
            yield ExecutorEvent(
                run_ref=run_ref,
                sequence=1,
                cursor="creator-create-project-succeeded",
                status="succeeded",
                text_result="Creator project created.",
                detail={
                    "project_ref": {
                        "schema_version": 1,
                        "app_id": APP_ID,
                        "project_id": record.project_id,
                        "kind": "creator-project",
                        "revision": 1,
                    },
                },
            )

    async def command(
        self,
        submission: TaskSubmission,
        command: TaskCommand,
    ) -> CommandLookup:
        if command.task_id != submission.handle.task_id:
            raise TaskStoreError(
                "creator_create_project_command_task_mismatch"
            )
        record, _ = await asyncio.to_thread(
            self._read,
            self._services(),
            submission,
        )
        if record is None:
            return CommandLookup(state="not_found")
        return CommandLookup(
            state="rejected",
            reason=(
                "answer_unsupported"
                if command.kind == "answer"
                else "task_terminal"
            ),
        )

    async def query_command(
        self,
        submission: TaskSubmission,
        command: TaskCommand,
    ) -> CommandLookup:
        return await self.command(submission, command)


class CreatorMediaSubmission(StrictRuntimeModel):
    """Creator-side acceptance fact for one Host submission identity."""

    schema_version: Literal[1] = 1
    submission_id: str = Field(min_length=1, max_length=256)
    meaning_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_id: str = Field(min_length=1, max_length=192)
    target_ref: str = Field(min_length=1, max_length=200)
    state: Literal["prepared", "accepted", "failed"] = "prepared"
    creator_task_id: str | None = None
    failure_code: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CreatorMediaCommandReceipt(StrictRuntimeModel):
    """Durable result for one exact Host command identity."""

    schema_version: Literal[1] = 1
    command_id: str = Field(min_length=1, max_length=256)
    meaning_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["prepared", "accepted", "rejected"] = "prepared"
    reason: str | None = Field(default=None, min_length=1, max_length=256)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class _CreatorMediaTaskAdapter:
    """Project one Creator media Task/Attempt ledger onto Host protocol 1."""

    submission_protocol_version = 1
    action_id: str
    executor_id: str
    storage_key: str
    media_name: str
    task_kind: TaskKind

    def __init__(
        self,
        services: Callable[[], CreatorFileServices],
        *,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self._services = services
        self.poll_interval_seconds = float(poll_interval_seconds)

    async def aclose(self) -> None:
        """The App lifecycle, rather than each Host binding, owns services."""

    def action_descriptor(self) -> ActionDescriptor:
        raise NotImplementedError

    async def _dispatch(
        self,
        services: CreatorFileServices,
        record: CreatorMediaSubmission,
    ) -> FileImageDispatch | FileR2VDispatch:
        raise NotImplementedError

    def _notify_terminal(
        self,
        services: CreatorFileServices,
        task: TaskRecord,
    ) -> None:
        raise NotImplementedError

    def _code(self, suffix: str) -> str:
        return f"creator_{self.storage_key}_{suffix}"

    def _validate(self, submission: TaskSubmission) -> tuple[str, str, str]:
        descriptor = self.action_descriptor()
        if (
            submission.action.descriptor_digest != descriptor.descriptor_digest
            or submission.handle.action_id != self.action_id
            or submission.handle.descriptor_digest
            != descriptor.descriptor_digest
        ):
            raise TaskStoreError(self._code("action_mismatch"))
        descriptor.validate_inputs(submission.inputs)
        if submission.handle.scope.app_id != APP_ID:
            raise TaskStoreError(self._code("scope_mismatch"))
        submission_id = require_safe_runtime_segment(
            submission.handle.submission_id,
            label="Host submission_id",
        )
        return (
            submission_id,
            str(submission.inputs["project_id"]),
            str(submission.inputs["target_ref"]),
        )

    @staticmethod
    def _meaning(submission: TaskSubmission) -> str:
        return content_digest(
            {
                "task_id": submission.handle.task_id,
                "scope": submission.handle.scope.model_dump(mode="json"),
                "origin": submission.handle.origin.model_dump(mode="json"),
                "action": submission.action.descriptor_digest,
                "inputs": submission.inputs,
            },
        )

    def _submission_store(
        self,
        services: CreatorFileServices,
        submission_id: str,
    ) -> AtomicJsonRecordStore[CreatorMediaSubmission]:
        return AtomicJsonRecordStore(
            services.root
            / ".pawapp"
            / f"{self.storage_key}-submissions"
            / f"{submission_id}.json",
            CreatorMediaSubmission,
        )

    def _command_store(
        self,
        services: CreatorFileServices,
        submission_id: str,
        command_id: str,
    ) -> AtomicJsonRecordStore[CreatorMediaCommandReceipt]:
        command_id = require_safe_runtime_segment(
            command_id,
            label="Host command_id",
        )
        return AtomicJsonRecordStore(
            services.root
            / ".pawapp"
            / f"{self.storage_key}-commands"
            / submission_id
            / f"{command_id}.json",
            CreatorMediaCommandReceipt,
        )

    def _prepare(
        self,
        services: CreatorFileServices,
        submission: TaskSubmission,
    ) -> CreatorMediaSubmission:
        submission_id, project_id, target_ref = self._validate(submission)
        candidate = CreatorMediaSubmission(
            submission_id=submission_id,
            meaning_digest=self._meaning(submission),
            project_id=project_id,
            target_ref=target_ref,
        )
        store = self._submission_store(services, submission_id)
        created = store.try_create(candidate)
        current = created.value if created is not None else store.read()
        if (
            current.submission_id != submission_id
            or current.meaning_digest != candidate.meaning_digest
            or current.project_id != project_id
            or current.target_ref != target_ref
        ):
            raise TaskStoreError(self._code("submission_conflict"))
        return current

    def _read_submission(
        self,
        services: CreatorFileServices,
        submission: TaskSubmission,
        *,
        required: bool,
    ) -> CreatorMediaSubmission | None:
        submission_id, project_id, target_ref = self._validate(submission)
        record = self._submission_store(
            services,
            submission_id,
        ).read_or_none()
        if record is None:
            if required:
                raise TaskStoreError(self._code("submission_missing"))
            return None
        if (
            record.submission_id != submission_id
            or record.meaning_digest != self._meaning(submission)
            or record.project_id != project_id
            or record.target_ref != target_ref
        ):
            raise TaskStoreError(self._code("submission_conflict"))
        return record

    def _transition(
        self,
        services: CreatorFileServices,
        record: CreatorMediaSubmission,
        *,
        state: Literal["accepted", "failed"],
        creator_task_id: str | None = None,
        failure_code: str | None = None,
    ) -> CreatorMediaSubmission:
        store = self._submission_store(services, record.submission_id)

        def update(current: CreatorMediaSubmission):
            if current.meaning_digest != record.meaning_digest:
                raise TaskStoreError(self._code("submission_conflict"))
            if current.state != "prepared":
                if (
                    current.state == state
                    and current.creator_task_id == creator_task_id
                    and current.failure_code == failure_code
                ):
                    return current
                raise TaskStoreError(self._code("submission_conflict"))
            return current.model_copy(
                update={
                    "state": state,
                    "creator_task_id": creator_task_id,
                    "failure_code": failure_code,
                    "updated_at": utc_now(),
                },
            )

        return store.update(update).value

    def _run_ref(self, record: CreatorMediaSubmission) -> ExecutorRunRef:
        return ExecutorRunRef(
            executor_id=self.executor_id,
            session_id=record.project_id,
            run_id=record.submission_id,
        )

    @staticmethod
    def _execution_store(
        services: CreatorFileServices,
    ) -> ProjectExecutionStore:
        return ProjectExecutionStore(services.root)

    def _mapped_task(
        self,
        services: CreatorFileServices,
        record: CreatorMediaSubmission,
    ) -> TaskRecord:
        if record.state != "accepted" or not record.creator_task_id:
            raise TaskStoreError(self._code("task_unavailable"))
        try:
            task = self._execution_store(services).get_task(
                record.project_id,
                record.creator_task_id,
            )
        except RecordNotFoundError:
            raise TaskStoreError(self._code("task_unavailable")) from None
        if (
            task.kind is not self.task_kind
            or task.metadata.get("targetRef") != record.target_ref
        ):
            raise TaskStoreError(self._code("task_mismatch"))
        return task

    async def readiness(
        self,
        scope: TaskScope,
        inputs: dict,
    ) -> Readiness:
        if scope.app_id != APP_ID:
            return Readiness(
                state="blocked",
                reason=self._code("scope_mismatch"),
            )
        try:
            self.action_descriptor().validate_inputs(inputs)
            services = self._services()
            snapshot = await asyncio.to_thread(
                services.projects.read,
                str(inputs["project_id"]),
            )
            element_id = str(inputs["target_ref"]).removeprefix("element:")
            found = any(
                element_id in timeline.elements_by_id
                for timeline in snapshot.project.timelines.items.values()
            )
            if not found:
                return Readiness(
                    state="blocked",
                    reason=self._code("target_missing"),
                )
            tasks = await asyncio.to_thread(
                self._execution_store(services).list_tasks,
                str(inputs["project_id"]),
            )
            busy = any(
                item.kind is self.task_kind
                and item.status not in _TERMINAL
                and item.metadata.get("targetRef") == inputs["target_ref"]
                for item in tasks
            )
            return Readiness(
                state="blocked" if busy else "ready",
                reason=self._code("target_busy") if busy else None,
            )
        except Exception:  # noqa: BLE001
            return Readiness(
                state="blocked",
                reason="creator_project_unavailable",
            )

    async def submit(self, submission: TaskSubmission) -> ExecutorRunRef:
        services = self._services()
        record = await asyncio.to_thread(self._prepare, services, submission)
        if record.state in {"accepted", "failed"}:
            return self._run_ref(record)
        try:
            dispatch = await self._dispatch(services, record)
        except CreatorError as error:
            record = await asyncio.to_thread(
                self._transition,
                services,
                record,
                state="failed",
                failure_code=str(error.code).casefold(),
            )
            return self._run_ref(record)
        record = await asyncio.to_thread(
            self._transition,
            services,
            record,
            state="accepted",
            creator_task_id=dispatch.task_id,
        )
        return self._run_ref(record)

    async def query(self, submission: TaskSubmission) -> SubmissionLookup:
        services = self._services()
        record = await asyncio.to_thread(
            self._read_submission,
            services,
            submission,
            required=False,
        )
        if record is None:
            return SubmissionLookup(state="not_found")
        if record.state == "prepared":
            return SubmissionLookup(state="unknown")
        return SubmissionLookup(
            state="accepted",
            run_ref=self._run_ref(record),
        )

    @staticmethod
    def _host_status(status: TaskStatus) -> str:
        return {
            TaskStatus.QUEUED: "pending",
            TaskStatus.RUNNING: "running",
            TaskStatus.SUCCEEDED: "succeeded",
            TaskStatus.FAILED: "failed",
            TaskStatus.CANCELLED: "cancelled",
            TaskStatus.QUARANTINED: "failed",
        }[status]

    @staticmethod
    def _attempt_status(event: TaskAttemptEvent) -> str:
        return {
            "RUNNING": "running",
            "SUCCEEDED": "succeeded",
            "FAILED": "failed",
            "CANCELLED": "cancelled",
            "QUARANTINED": "failed",
        }[event.status.value]

    def _text(self, status: str, target_ref: str) -> str | None:
        if status == "running":
            return f"Creator is generating {self.media_name} for {target_ref}."
        if status == "succeeded":
            return f"Creator generated {self.media_name} for {target_ref}."
        if status == "cancelled":
            return (
                f"Creator {self.media_name} generation was cancelled for "
                f"{target_ref}."
            )
        if status == "failed":
            return (
                f"Creator {self.media_name} generation failed for "
                f"{target_ref}."
            )
        return None

    async def _project_detail(
        self,
        services: CreatorFileServices,
        record: CreatorMediaSubmission,
    ) -> dict:
        revision = 1
        if record.state != "failed":
            snapshot = await asyncio.to_thread(
                services.projects.read,
                record.project_id,
            )
            revision = max(1, int(snapshot.generation))
        return {
            "project_ref": {
                "schema_version": 1,
                "app_id": APP_ID,
                "project_id": record.project_id,
                "kind": "creator-project",
                "revision": revision,
            },
        }

    @staticmethod
    def _artifact_version_id(
        output: dict | None,
        output_refs: list[str] | None = None,
    ) -> str | None:
        payload = output or {}
        output_ref = payload.get("outputRef")
        if isinstance(output_ref, str) and output_ref.startswith(
            "artifact-version:",
        ):
            version_id = output_ref.removeprefix("artifact-version:")
            return version_id or None
        version_id = payload.get("artifactVersionId")
        if isinstance(version_id, str) and version_id:
            return version_id
        for candidate in output_refs or []:
            if candidate.startswith("artifact-version:"):
                version_id = candidate.removeprefix("artifact-version:")
                return version_id or None
        return None

    async def _terminal_detail(
        self,
        services: CreatorFileServices,
        record: CreatorMediaSubmission,
        *,
        output: dict | None,
        output_refs: list[str] | None = None,
    ) -> dict:
        version_id = self._artifact_version_id(output, output_refs)
        if version_id is None:
            raise TaskStoreError(self._code("artifact_missing"))
        detail = await self._project_detail(services, record)
        detail[_ARTIFACT_VERSION_DETAIL] = version_id
        return detail

    def _read_artifact(
        self,
        services: CreatorFileServices,
        record: CreatorMediaSubmission,
        version_id: str,
    ) -> tuple[dict, bytes]:
        snapshot = services.projects.read(record.project_id)
        version = snapshot.project.assets.artifact_versions_by_id.get(
            version_id,
        )
        if version is None:
            raise TaskStoreError(self._code("artifact_missing"))
        indexed = snapshot.project.assets.files_by_id.get(version.file_id)
        if indexed is None:
            raise TaskStoreError(self._code("artifact_missing"))
        try:
            artifact = read_verified_creator_artifact(
                services.projects.project_root(record.project_id),
                version=version,
                indexed=indexed,
                expected_owner_ref=record.target_ref,
                expected_task_id=record.creator_task_id,
            )
        except CreatorArtifactMismatch:
            raise TaskStoreError(self._code("artifact_mismatch")) from None
        except CreatorArtifactUnavailable:
            raise TaskStoreError(self._code("artifact_unavailable")) from None
        return artifact.source, artifact.content

    async def materialize_event(self, submission, event, artifacts):
        """Publish one exact Creator output through Host artifact storage."""
        version_id = event.detail.get(_ARTIFACT_VERSION_DETAIL)
        if version_id is None:
            return event
        if event.status != "succeeded" or not isinstance(version_id, str):
            raise TaskStoreError(self._code("artifact_mismatch"))
        services = self._services()
        record = await asyncio.to_thread(
            self._read_submission,
            services,
            submission,
            required=True,
        )
        assert record is not None
        source, content = await asyncio.to_thread(
            self._read_artifact,
            services,
            record,
            version_id,
        )
        ref = await artifacts.publish(submission, source, content)
        detail = dict(event.detail)
        detail.pop(_ARTIFACT_VERSION_DETAIL, None)
        detail["artifact_ref"] = ref.model_dump(mode="json")
        return event.model_copy(update={"detail": detail})

    async def attach(self, submission: TaskSubmission):
        services = self._services()
        record = await asyncio.to_thread(
            self._read_submission,
            services,
            submission,
            required=True,
        )
        assert record is not None
        run_ref = self._run_ref(record)
        after = submission.handle.executor_sequence
        after = -1 if after is None else after
        detail = await self._project_detail(services, record)
        if record.state == "failed":
            if after < 0:
                yield ExecutorEvent(
                    run_ref=run_ref,
                    sequence=0,
                    cursor=f"creator-{self.storage_key}-failed",
                    status="failed",
                    text_result=(
                        "Creator could not admit the "
                        f"{self.media_name} generation task."
                    ),
                    detail={
                        **detail,
                        "reason_code": record.failure_code or "creator_error",
                    },
                )
            return
        if record.state != "accepted":
            raise TaskStoreError(self._code("submission_unknown"))

        while True:
            task = await asyncio.to_thread(
                self._mapped_task,
                services,
                record,
            )
            attempts = await asyncio.to_thread(
                self._execution_store(services).list_task_attempts,
                record.project_id,
                task.task_id,
            )
            if after < 0 and not attempts:
                yield ExecutorEvent(
                    run_ref=run_ref,
                    sequence=0,
                    cursor=f"creator-{self.storage_key}-queued",
                    status="pending",
                    detail=detail,
                )
                after = 0
            for event in attempts:
                if event.attempt_seq <= after:
                    continue
                status = self._attempt_status(event)
                event_detail = detail
                if status == "succeeded":
                    event_detail = await self._terminal_detail(
                        services,
                        record,
                        output=event.output,
                        output_refs=event.output_refs,
                    )
                yield ExecutorEvent(
                    run_ref=run_ref,
                    sequence=event.attempt_seq,
                    cursor=(
                        f"creator-{self.storage_key}-attempt-"
                        f"{event.attempt_seq}"
                    ),
                    status=status,
                    text_result=self._text(status, record.target_ref),
                    detail=event_detail,
                )
                after = event.attempt_seq
            task_status = self._host_status(task.status)
            if task.status in _TERMINAL:
                final_attempt_status = (
                    self._attempt_status(attempts[-1]) if attempts else None
                )
                if final_attempt_status != task_status:
                    sequence = max(after + 1, task.last_attempt_seq + 1)
                    terminal_detail = detail
                    if task_status == "succeeded":
                        terminal_detail = await self._terminal_detail(
                            services,
                            record,
                            output=task.result,
                            output_refs=task.output_refs,
                        )
                    yield ExecutorEvent(
                        run_ref=run_ref,
                        sequence=sequence,
                        cursor=(
                            f"creator-{self.storage_key}-terminal-"
                            + task.status.value.casefold()
                        ),
                        status=task_status,
                        text_result=self._text(task_status, record.target_ref),
                        detail=terminal_detail,
                    )
                return
            await asyncio.sleep(self.poll_interval_seconds)

    def _cancel(
        self,
        services: CreatorFileServices,
        record: CreatorMediaSubmission,
        reason: str,
    ) -> CommandLookup:
        if record.state != "accepted":
            return CommandLookup(state="rejected", reason="task_terminal")
        task = self._mapped_task(services, record)
        if task.status is TaskStatus.CANCELLED:
            return CommandLookup(state="accepted")
        if task.status in _TERMINAL:
            return CommandLookup(state="rejected", reason="task_terminal")
        executions = self._execution_store(services)
        with services.projects.lifecycle_lock(record.project_id):
            services.projects.read(record.project_id)
            task = executions.get_task(
                record.project_id,
                task.task_id,
                _lifecycle_lock_held=True,
            )
            if task.status is TaskStatus.CANCELLED:
                return CommandLookup(state="accepted")
            if task.status in _TERMINAL:
                return CommandLookup(
                    state="rejected",
                    reason="task_terminal",
                )
            task = executions.transition_task(
                record.project_id,
                task.task_id,
                expected_status={TaskStatus.QUEUED, TaskStatus.RUNNING},
                status=TaskStatus.CANCELLED,
                updates={
                    "error": {
                        "code": "HOST_CANCELLED",
                        "message": (reason or "Host requested cancellation")[
                            :1000
                        ],
                    },
                },
                _lifecycle_lock_held=True,
            )
        self._notify_terminal(services, task)
        return CommandLookup(state="accepted")

    @staticmethod
    def _command_meaning(command: TaskCommand) -> str:
        return content_digest(
            {
                "task_id": command.task_id,
                "command_id": command.command_id,
                "kind": command.kind,
                "request_id": command.request_id,
                "payload": command.payload,
            },
        )

    def _prepare_command(
        self,
        services: CreatorFileServices,
        record: CreatorMediaSubmission,
        command: TaskCommand,
    ) -> CreatorMediaCommandReceipt:
        command_id = require_safe_runtime_segment(
            command.command_id,
            label="Host command_id",
        )
        candidate = CreatorMediaCommandReceipt(
            command_id=command_id,
            meaning_digest=self._command_meaning(command),
        )
        store = self._command_store(
            services,
            record.submission_id,
            command_id,
        )
        created = store.try_create(candidate)
        current = created.value if created is not None else store.read()
        if (
            current.command_id != command_id
            or current.meaning_digest != candidate.meaning_digest
        ):
            raise TaskStoreError(self._code("command_conflict"))
        return current

    def _read_command(
        self,
        services: CreatorFileServices,
        record: CreatorMediaSubmission,
        command: TaskCommand,
    ) -> CreatorMediaCommandReceipt | None:
        command_id = require_safe_runtime_segment(
            command.command_id,
            label="Host command_id",
        )
        receipt = self._command_store(
            services,
            record.submission_id,
            command_id,
        ).read_or_none()
        if receipt is not None and (
            receipt.command_id != command_id
            or receipt.meaning_digest != self._command_meaning(command)
        ):
            raise TaskStoreError(self._code("command_conflict"))
        return receipt

    def _transition_command(
        self,
        services: CreatorFileServices,
        record: CreatorMediaSubmission,
        receipt: CreatorMediaCommandReceipt,
        result: CommandLookup,
    ) -> CreatorMediaCommandReceipt:
        if result.state not in {"accepted", "rejected"}:
            raise TaskStoreError(self._code("command_not_terminal"))
        store = self._command_store(
            services,
            record.submission_id,
            receipt.command_id,
        )

        def update(current: CreatorMediaCommandReceipt):
            if current.meaning_digest != receipt.meaning_digest:
                raise TaskStoreError(self._code("command_conflict"))
            if current.state != "prepared":
                if (
                    current.state == result.state
                    and current.reason == result.reason
                ):
                    return current
                raise TaskStoreError(self._code("command_conflict"))
            return current.model_copy(
                update={
                    "state": result.state,
                    "reason": result.reason,
                    "updated_at": utc_now(),
                },
            )

        return store.update(update).value

    def _execute_command(
        self,
        services: CreatorFileServices,
        record: CreatorMediaSubmission,
        command: TaskCommand,
        receipt: CreatorMediaCommandReceipt,
    ) -> CommandLookup:
        if receipt.state != "prepared":
            return CommandLookup(state=receipt.state, reason=receipt.reason)
        result = (
            CommandLookup(state="rejected", reason="answer_unsupported")
            if command.kind == "answer"
            else self._cancel(
                services,
                record,
                str(command.payload.get("reason") or ""),
            )
        )
        receipt = self._transition_command(
            services,
            record,
            receipt,
            result,
        )
        return CommandLookup(state=receipt.state, reason=receipt.reason)

    async def command(
        self,
        submission: TaskSubmission,
        command: TaskCommand,
    ) -> CommandLookup:
        if command.task_id != submission.handle.task_id:
            raise TaskStoreError(self._code("command_task_mismatch"))
        services = self._services()
        record = await asyncio.to_thread(
            self._read_submission,
            services,
            submission,
            required=True,
        )
        assert record is not None
        receipt = await asyncio.to_thread(
            self._prepare_command,
            services,
            record,
            command,
        )
        return await asyncio.to_thread(
            self._execute_command,
            services,
            record,
            command,
            receipt,
        )

    async def query_command(
        self,
        submission: TaskSubmission,
        command: TaskCommand,
    ) -> CommandLookup:
        if command.task_id != submission.handle.task_id:
            raise TaskStoreError(self._code("command_task_mismatch"))
        services = self._services()
        record = await asyncio.to_thread(
            self._read_submission,
            services,
            submission,
            required=False,
        )
        if record is None:
            return CommandLookup(state="not_found")
        receipt = await asyncio.to_thread(
            self._read_command,
            services,
            record,
            command,
        )
        if receipt is None:
            return CommandLookup(state="not_found")
        return await asyncio.to_thread(
            self._execute_command,
            services,
            record,
            command,
            receipt,
        )


class CreatorVideoTaskAdapter(_CreatorMediaTaskAdapter):
    """Project Creator's R2V ledger onto Host protocol 1."""

    action_id = VIDEO_ACTION_ID
    executor_id = VIDEO_EXECUTOR_ID
    storage_key = "video"
    media_name = "video"
    media_type_prefix = "video/"
    task_kind = TaskKind.R2V_GENERATION

    def action_descriptor(self) -> ActionDescriptor:
        return creator_video_action_descriptor()

    async def _dispatch(
        self,
        services: CreatorFileServices,
        record: CreatorMediaSubmission,
    ) -> FileR2VDispatch:
        return await execute_file_r2v_command(
            services,
            project_id=record.project_id,
            target_ref=record.target_ref,
            arguments={},
            idempotency_key=record.submission_id,
        )

    def _notify_terminal(
        self,
        services: CreatorFileServices,
        task: TaskRecord,
    ) -> None:
        file_r2v_execution_service(services).notify_terminal_task(task)


class CreatorStoryboardTaskAdapter(_CreatorMediaTaskAdapter):
    """Project Creator's storyboard-image ledger onto Host protocol 1."""

    action_id = STORYBOARD_ACTION_ID
    executor_id = STORYBOARD_EXECUTOR_ID
    storage_key = "storyboard"
    media_name = "storyboard"
    media_type_prefix = "image/"
    task_kind = TaskKind.IMAGE_GENERATION

    def action_descriptor(self) -> ActionDescriptor:
        return creator_storyboard_action_descriptor()

    async def _dispatch(
        self,
        services: CreatorFileServices,
        record: CreatorMediaSubmission,
    ) -> FileImageDispatch:
        return await dispatch_file_image_command(
            services,
            project_id=record.project_id,
            command=CreatorCommandType.GENERATE_STORYBOARD_IMAGE,
            target_ref=record.target_ref,
            arguments={},
            idempotency_key=record.submission_id,
        )

    def _notify_terminal(
        self,
        services: CreatorFileServices,
        task: TaskRecord,
    ) -> None:
        file_image_execution_service(services).notify_terminal_task(task)


__all__ = [
    "CreatorCreateProjectTaskAdapter",
    "CreatorStoryboardTaskAdapter",
    "CreatorVideoTaskAdapter",
    "creator_create_project_action_descriptor",
    "creator_storyboard_action_descriptor",
    "creator_video_action_descriptor",
]
