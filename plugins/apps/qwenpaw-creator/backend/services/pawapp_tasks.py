# -*- coding: utf-8 -*-
"""Protocol-1 Host task adapter for Creator's durable video runtime."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from pydantic import Field

from domain.enums import TaskKind, TaskStatus
from domain.errors import CreatorError
from services.media_files.r2v_execution import (
    execute_file_r2v_command,
    file_r2v_execution_service,
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
ACTION_ID = "generate-video"
EXECUTOR_ID = "qwenpaw-creator.video"
_TERMINAL = {
    TaskStatus.SUCCEEDED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.QUARANTINED,
}


def creator_video_action_descriptor() -> ActionDescriptor:
    """Describe generation from one committed storyboard-backed element."""
    return ActionDescriptor(
        app_id=APP_ID,
        action_id=ACTION_ID,
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
        output_types=("text/plain",),
        permissions=(
            "creator.project.read",
            "creator.project.write",
            "creator.video.generate",
        ),
        effects=("model_usage", "project_mutation"),
        adapter_ref="qwenpaw-creator.video-generation.v1",
    )


class CreatorVideoSubmission(StrictRuntimeModel):
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


class CreatorVideoCommandReceipt(StrictRuntimeModel):
    """Durable result for one exact Host command identity."""

    schema_version: Literal[1] = 1
    command_id: str = Field(min_length=1, max_length=256)
    meaning_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["prepared", "accepted", "rejected"] = "prepared"
    reason: str | None = Field(default=None, min_length=1, max_length=256)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CreatorVideoTaskAdapter:
    """Project the existing R2V Task/Attempt ledger onto Host protocol 1."""

    submission_protocol_version = 1

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

    @staticmethod
    def _validate(submission: TaskSubmission) -> tuple[str, str, str]:
        descriptor = creator_video_action_descriptor()
        if (
            submission.action.descriptor_digest != descriptor.descriptor_digest
            or submission.handle.action_id != ACTION_ID
            or submission.handle.descriptor_digest
            != descriptor.descriptor_digest
        ):
            raise TaskStoreError("creator_video_action_mismatch")
        descriptor.validate_inputs(submission.inputs)
        if submission.handle.scope.app_id != APP_ID:
            raise TaskStoreError("creator_video_scope_mismatch")
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
    ) -> AtomicJsonRecordStore[CreatorVideoSubmission]:
        return AtomicJsonRecordStore(
            services.root
            / ".pawapp"
            / "video-submissions"
            / f"{submission_id}.json",
            CreatorVideoSubmission,
        )

    def _command_store(
        self,
        services: CreatorFileServices,
        submission_id: str,
        command_id: str,
    ) -> AtomicJsonRecordStore[CreatorVideoCommandReceipt]:
        command_id = require_safe_runtime_segment(
            command_id,
            label="Host command_id",
        )
        return AtomicJsonRecordStore(
            services.root
            / ".pawapp"
            / "video-commands"
            / submission_id
            / f"{command_id}.json",
            CreatorVideoCommandReceipt,
        )

    def _prepare(
        self,
        services: CreatorFileServices,
        submission: TaskSubmission,
    ) -> CreatorVideoSubmission:
        submission_id, project_id, target_ref = self._validate(submission)
        candidate = CreatorVideoSubmission(
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
            raise TaskStoreError("creator_video_submission_conflict")
        return current

    def _read_submission(
        self,
        services: CreatorFileServices,
        submission: TaskSubmission,
        *,
        required: bool,
    ) -> CreatorVideoSubmission | None:
        submission_id, project_id, target_ref = self._validate(submission)
        record = self._submission_store(
            services,
            submission_id,
        ).read_or_none()
        if record is None:
            if required:
                raise TaskStoreError("creator_video_submission_missing")
            return None
        if (
            record.submission_id != submission_id
            or record.meaning_digest != self._meaning(submission)
            or record.project_id != project_id
            or record.target_ref != target_ref
        ):
            raise TaskStoreError("creator_video_submission_conflict")
        return record

    def _transition(
        self,
        services: CreatorFileServices,
        record: CreatorVideoSubmission,
        *,
        state: Literal["accepted", "failed"],
        creator_task_id: str | None = None,
        failure_code: str | None = None,
    ) -> CreatorVideoSubmission:
        store = self._submission_store(services, record.submission_id)

        def update(current: CreatorVideoSubmission):
            if current.meaning_digest != record.meaning_digest:
                raise TaskStoreError("creator_video_submission_conflict")
            if current.state != "prepared":
                if (
                    current.state == state
                    and current.creator_task_id == creator_task_id
                    and current.failure_code == failure_code
                ):
                    return current
                raise TaskStoreError("creator_video_submission_conflict")
            return current.model_copy(
                update={
                    "state": state,
                    "creator_task_id": creator_task_id,
                    "failure_code": failure_code,
                    "updated_at": utc_now(),
                },
            )

        return store.update(update).value

    @staticmethod
    def _run_ref(record: CreatorVideoSubmission) -> ExecutorRunRef:
        return ExecutorRunRef(
            executor_id=EXECUTOR_ID,
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
        record: CreatorVideoSubmission,
    ) -> TaskRecord:
        if record.state != "accepted" or not record.creator_task_id:
            raise TaskStoreError("creator_video_task_unavailable")
        try:
            task = self._execution_store(services).get_task(
                record.project_id,
                record.creator_task_id,
            )
        except RecordNotFoundError:
            raise TaskStoreError("creator_video_task_unavailable") from None
        if (
            task.kind is not TaskKind.R2V_GENERATION
            or task.metadata.get("targetRef") != record.target_ref
        ):
            raise TaskStoreError("creator_video_task_mismatch")
        return task

    async def readiness(
        self,
        scope: TaskScope,
        inputs: dict,
    ) -> Readiness:
        if scope.app_id != APP_ID:
            return Readiness(
                state="blocked",
                reason="creator_video_scope_mismatch",
            )
        try:
            creator_video_action_descriptor().validate_inputs(inputs)
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
                    reason="creator_video_target_missing",
                )
            tasks = await asyncio.to_thread(
                self._execution_store(services).list_tasks,
                str(inputs["project_id"]),
            )
            busy = any(
                item.kind is TaskKind.R2V_GENERATION
                and item.status not in _TERMINAL
                and item.metadata.get("targetRef") == inputs["target_ref"]
                for item in tasks
            )
            return Readiness(
                state="blocked" if busy else "ready",
                reason="creator_video_target_busy" if busy else None,
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
            dispatch = await execute_file_r2v_command(
                services,
                project_id=record.project_id,
                target_ref=record.target_ref,
                arguments={},
                idempotency_key=record.submission_id,
            )
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

    @staticmethod
    def _text(status: str, target_ref: str) -> str | None:
        if status == "running":
            return f"Creator is generating video for {target_ref}."
        if status == "succeeded":
            return f"Creator generated video for {target_ref}."
        if status == "cancelled":
            return f"Creator video generation was cancelled for {target_ref}."
        if status == "failed":
            return f"Creator video generation failed for {target_ref}."
        return None

    async def _project_detail(
        self,
        services: CreatorFileServices,
        record: CreatorVideoSubmission,
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
                    cursor="creator-video-failed",
                    status="failed",
                    text_result=(
                        "Creator could not admit the video generation task."
                    ),
                    detail={
                        **detail,
                        "reason_code": record.failure_code or "creator_error",
                    },
                )
            return
        if record.state != "accepted":
            raise TaskStoreError("creator_video_submission_unknown")

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
                    cursor="creator-video-queued",
                    status="pending",
                    detail=detail,
                )
                after = 0
            for event in attempts:
                if event.attempt_seq <= after:
                    continue
                status = self._attempt_status(event)
                yield ExecutorEvent(
                    run_ref=run_ref,
                    sequence=event.attempt_seq,
                    cursor=f"creator-video-attempt-{event.attempt_seq}",
                    status=status,
                    text_result=self._text(status, record.target_ref),
                    detail=detail,
                )
                after = event.attempt_seq
            task_status = self._host_status(task.status)
            if task.status in _TERMINAL:
                final_attempt_status = (
                    self._attempt_status(attempts[-1]) if attempts else None
                )
                if final_attempt_status != task_status:
                    sequence = max(after + 1, task.last_attempt_seq + 1)
                    yield ExecutorEvent(
                        run_ref=run_ref,
                        sequence=sequence,
                        cursor=(
                            "creator-video-terminal-"
                            + task.status.value.casefold()
                        ),
                        status=task_status,
                        text_result=self._text(task_status, record.target_ref),
                        detail=detail,
                    )
                return
            await asyncio.sleep(self.poll_interval_seconds)

    def _cancel(
        self,
        services: CreatorFileServices,
        record: CreatorVideoSubmission,
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
        file_r2v_execution_service(services).notify_terminal_task(task)
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
        record: CreatorVideoSubmission,
        command: TaskCommand,
    ) -> CreatorVideoCommandReceipt:
        command_id = require_safe_runtime_segment(
            command.command_id,
            label="Host command_id",
        )
        candidate = CreatorVideoCommandReceipt(
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
            raise TaskStoreError("creator_video_command_conflict")
        return current

    def _read_command(
        self,
        services: CreatorFileServices,
        record: CreatorVideoSubmission,
        command: TaskCommand,
    ) -> CreatorVideoCommandReceipt | None:
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
            raise TaskStoreError("creator_video_command_conflict")
        return receipt

    def _transition_command(
        self,
        services: CreatorFileServices,
        record: CreatorVideoSubmission,
        receipt: CreatorVideoCommandReceipt,
        result: CommandLookup,
    ) -> CreatorVideoCommandReceipt:
        if result.state not in {"accepted", "rejected"}:
            raise TaskStoreError("creator_video_command_not_terminal")
        store = self._command_store(
            services,
            record.submission_id,
            receipt.command_id,
        )

        def update(current: CreatorVideoCommandReceipt):
            if current.meaning_digest != receipt.meaning_digest:
                raise TaskStoreError("creator_video_command_conflict")
            if current.state != "prepared":
                if (
                    current.state == result.state
                    and current.reason == result.reason
                ):
                    return current
                raise TaskStoreError("creator_video_command_conflict")
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
        record: CreatorVideoSubmission,
        command: TaskCommand,
        receipt: CreatorVideoCommandReceipt,
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
            raise TaskStoreError("creator_video_command_task_mismatch")
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
            raise TaskStoreError("creator_video_command_task_mismatch")
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


__all__ = [
    "CreatorVideoTaskAdapter",
    "creator_video_action_descriptor",
]
