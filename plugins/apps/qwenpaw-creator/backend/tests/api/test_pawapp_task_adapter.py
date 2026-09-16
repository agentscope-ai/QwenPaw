# -*- coding: utf-8 -*-
"""Protocol-1 projection of Creator's durable R2V task ledger."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from domain.enums import TaskKind, TaskStatus
from domain.errors import ValidationError
from services import pawapp_tasks
from services.project_files.facade import CreatorFileServices
from services.project_files.models import (
    ElementLocation,
    Project,
    R2VCreation,
    TimelineElement,
    TimelineSpan,
)
from services.runtime_files.execution_models import TaskRecord
from services.runtime_files.execution_store import ProjectExecutionStore

from qwenpaw.pawapp.tasks import (
    ActionDescriptor,
    TaskCommand,
    TaskHandle,
    TaskOrigin,
    TaskScope,
    TaskStoreError,
    TaskSubmission,
)

PROJECT_ID = "creator-project-1"
TARGET_REF = "element:shot-1"


def test_registered_contract_matches_design_fixture() -> None:
    path = (
        Path(__file__).resolve().parents[6]
        / "docs/design/pawapp-vnext-creator-video-action.example.json"
    )

    assert pawapp_tasks.creator_video_action_descriptor() == (
        ActionDescriptor.model_validate_json(path.read_text(encoding="utf-8"))
    )


def _services(tmp_path: Path) -> CreatorFileServices:
    services = CreatorFileServices.create(tmp_path.resolve())
    project = Project.new(project_id=PROJECT_ID, name="Creator Project")
    project.timelines.items["timeline:main"].elements_by_id[
        "shot-1"
    ] = TimelineElement(
        element_id="shot-1",
        label="Shot 1",
        span=TimelineSpan(start_tick=0, duration_tick=4_000),
        location=ElementLocation(),
        creation=R2VCreation(
            narrative="A cat runs through the frame.",
            storyboard_prompt="A cat running.",
            video_prompt="A cat runs from left to right.",
        ),
    )
    services.projects.create(project)
    return services


def _submission(submission_id: str = "submission-1") -> TaskSubmission:
    action = pawapp_tasks.creator_video_action_descriptor()
    scope = TaskScope(
        principal_id="alice",
        workspace_id="workspace-1",
        app_id=pawapp_tasks.APP_ID,
    )
    return TaskSubmission(
        handle=TaskHandle(
            task_id="host-task-1",
            submission_id=submission_id,
            scope=scope,
            action_id=action.action_id,
            descriptor_digest=action.descriptor_digest,
            origin=TaskOrigin(
                engagement="delegated",
                origin_ref="chat-1",
                return_session_ref="chat-1",
            ),
            created_at=1000,
            updated_at=1000,
        ),
        action=action,
        inputs={"project_id": PROJECT_ID, "target_ref": TARGET_REF},
    )


class _FakeR2VService:
    def __init__(
        self,
        services: CreatorFileServices,
        *,
        error: Exception | None = None,
    ) -> None:
        self.services = services
        self.error = error
        self.dispatches = 0
        self.notifications = []

    async def dispatch(self, **kwargs):
        self.dispatches += 1
        if self.error is not None:
            raise self.error
        task_id = "creator-video-task-1"
        store = ProjectExecutionStore(self.services.root)
        store.create_task(
            TaskRecord(
                task_id=task_id,
                project_id=kwargs["project_id"],
                kind=TaskKind.R2V_GENERATION,
                request_fingerprint="sha256:request",
                idempotency_key=kwargs["idempotency_key"],
                metadata={"targetRef": kwargs["target_ref"]},
            ),
        )
        return SimpleNamespace(task_id=task_id)

    def notify_terminal_task(self, task: TaskRecord):
        self.notifications.append(task.task_id)


@pytest.mark.asyncio
async def test_submit_is_durable_and_replays_one_creator_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    runtime = _FakeR2VService(services)
    monkeypatch.setattr(
        pawapp_tasks,
        "file_r2v_execution_service",
        lambda _services: runtime,
    )
    adapter = pawapp_tasks.CreatorVideoTaskAdapter(lambda: services)
    submission = _submission()

    first = await adapter.submit(submission)
    second = await adapter.submit(submission)
    lookup = await adapter.query(submission)

    assert first == second
    assert first.executor_id == pawapp_tasks.EXECUTOR_ID
    assert first.session_id == PROJECT_ID
    assert first.run_id == submission.handle.submission_id
    assert runtime.dispatches == 1
    assert lookup.state == "accepted"
    assert lookup.run_ref == first


@pytest.mark.asyncio
async def test_attach_replays_attempts_and_terminal_project_reference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    runtime = _FakeR2VService(services)
    monkeypatch.setattr(
        pawapp_tasks,
        "file_r2v_execution_service",
        lambda _services: runtime,
    )
    adapter = pawapp_tasks.CreatorVideoTaskAdapter(
        lambda: services,
        poll_interval_seconds=0.01,
    )
    submission = _submission()
    run_ref = await adapter.submit(submission)
    store = ProjectExecutionStore(services.root)
    store.append_task_attempt(
        PROJECT_ID,
        "creator-video-task-1",
        event_id="attempt-started-1",
        attempt_id="attempt-1",
        status="RUNNING",
    )
    store.append_task_attempt(
        PROJECT_ID,
        "creator-video-task-1",
        event_id="attempt-succeeded-1",
        attempt_id="attempt-1",
        status="SUCCEEDED",
        output={"artifactVersionId": "video-version-1"},
    )

    events = [event async for event in adapter.attach(submission)]

    assert [event.sequence for event in events] == [1, 2]
    assert [event.status for event in events] == ["running", "succeeded"]
    assert all(event.run_ref == run_ref for event in events)
    assert events[-1].detail["project_ref"] == {
        "schema_version": 1,
        "app_id": pawapp_tasks.APP_ID,
        "project_id": PROJECT_ID,
        "kind": "creator-project",
        "revision": 1,
    }
    assert events[-1].text_result == (
        "Creator generated video for element:shot-1."
    )


@pytest.mark.asyncio
async def test_admission_failure_becomes_a_durable_terminal_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    runtime = _FakeR2VService(
        services,
        error=ValidationError("storyboard is missing"),
    )
    monkeypatch.setattr(
        pawapp_tasks,
        "file_r2v_execution_service",
        lambda _services: runtime,
    )
    adapter = pawapp_tasks.CreatorVideoTaskAdapter(lambda: services)
    submission = _submission()

    await adapter.submit(submission)
    lookup = await adapter.query(submission)
    events = [event async for event in adapter.attach(submission)]

    assert lookup.state == "accepted"
    assert len(events) == 1
    assert events[0].status == "failed"
    assert events[0].detail["reason_code"] == "validation_error"
    assert "storyboard is missing" not in events[0].model_dump_json()


@pytest.mark.asyncio
async def test_cancel_and_query_command_use_the_creator_task_head(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    runtime = _FakeR2VService(services)
    monkeypatch.setattr(
        pawapp_tasks,
        "file_r2v_execution_service",
        lambda _services: runtime,
    )
    adapter = pawapp_tasks.CreatorVideoTaskAdapter(lambda: services)
    submission = _submission()
    await adapter.submit(submission)
    command = TaskCommand(
        task_id=submission.handle.task_id,
        command_id="cancel-1",
        kind="cancel",
        payload={"reason": "No longer needed"},
        created_at=1001,
        updated_at=1001,
    )

    result = await adapter.command(submission, command)
    replay = await adapter.query_command(submission, command)
    task = ProjectExecutionStore(services.root).get_task(
        PROJECT_ID,
        "creator-video-task-1",
    )

    assert result.state == replay.state == "accepted"
    assert task.status is TaskStatus.CANCELLED
    assert runtime.notifications == ["creator-video-task-1"]

    unrelated = command.model_copy(update={"command_id": "cancel-2"})
    assert (
        await adapter.query_command(submission, unrelated)
    ).state == "not_found"

    conflict = command.model_copy(
        update={"payload": {"reason": "A different request"}},
    )
    with pytest.raises(
        TaskStoreError,
        match="creator_video_command_conflict",
    ):
        await adapter.query_command(submission, conflict)


@pytest.mark.asyncio
async def test_replay_rejects_changed_submission_meaning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    runtime = _FakeR2VService(services)
    monkeypatch.setattr(
        pawapp_tasks,
        "file_r2v_execution_service",
        lambda _services: runtime,
    )
    adapter = pawapp_tasks.CreatorVideoTaskAdapter(lambda: services)
    submission = _submission()
    await adapter.submit(submission)
    changed = submission.model_copy(
        update={
            "inputs": {
                "project_id": PROJECT_ID,
                "target_ref": "element:another-shot",
            },
        },
    )

    with pytest.raises(
        TaskStoreError,
        match="creator_video_submission_conflict",
    ):
        await adapter.query(changed)
    with pytest.raises(
        TaskStoreError,
        match="creator_video_submission_conflict",
    ):
        await anext(adapter.attach(changed))


@pytest.mark.asyncio
async def test_readiness_checks_project_target_and_busy_state(
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    adapter = pawapp_tasks.CreatorVideoTaskAdapter(lambda: services)
    submission = _submission()

    ready = await adapter.readiness(
        submission.handle.scope,
        submission.inputs,
    )
    assert ready.state == "ready"

    ProjectExecutionStore(services.root).create_task(
        TaskRecord(
            task_id="busy-video-task",
            project_id=PROJECT_ID,
            kind=TaskKind.R2V_GENERATION,
            request_fingerprint="sha256:busy",
            metadata={"targetRef": TARGET_REF},
        ),
    )
    busy = await adapter.readiness(
        submission.handle.scope,
        submission.inputs,
    )
    assert busy.state == "blocked"
    assert busy.reason == "creator_video_target_busy"
