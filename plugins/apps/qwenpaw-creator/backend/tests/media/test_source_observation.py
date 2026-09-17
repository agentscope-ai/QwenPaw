# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Tests for services.media.source_observation (observe_source_clip)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from domain.enums import TaskKind, TaskStatus
from domain.errors import ValidationError
from services.media import source_observation
from services.media.source_observation import (
    OBSERVE_MIN_WINDOW_MS,
    SourceObservationService,
)

# ── transport-aware clip encoding (moved with the implementation) ───────────


def test_clip_transport_prefers_hq_on_dashscope(tmp_path, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        source_observation.vlm_model,
        "uses_dashscope_transport",
        lambda: True,
    )
    monkeypatch.setattr(
        source_observation,
        "clip_segment_hq_sync",
        lambda *a: calls.append("hq") or a[1],
    )
    monkeypatch.setattr(
        source_observation,
        "clip_segment_within_budget_sync",
        lambda *a: calls.append("ladder") or a[1],
    )
    source_observation.clip_segment_for_transport_sync(
        tmp_path / "in.mp4",
        tmp_path / "out.mp4",
        0.0,
        10.0,
    )
    assert calls == ["hq"]


# ── observe_source_clip scheduling ──────────────────────────────────────────


def _project_snapshot(tmp_path: Path, *, with_file: bool = True):
    media = tmp_path / "projects" / "project-1" / "assets" / "clip.mp4"
    media.parent.mkdir(parents=True, exist_ok=True)
    if with_file:
        media.write_bytes(b"\x00" * 32)
    source = SimpleNamespace(
        logical_asset_id="asset-1",
        selected_asset_version_id="version-1",
    )
    version = SimpleNamespace(
        version_id="version-1",
        file_id="file-1",
    )
    indexed = SimpleNamespace(relative_uri="assets/clip.mp4")
    project = SimpleNamespace(
        sources=SimpleNamespace(
            sources=SimpleNamespace(items={"source-1": source}),
        ),
        assets=SimpleNamespace(
            source_versions_by_id={"version-1": version},
            files_by_id={"file-1": indexed},
        ),
    )
    return SimpleNamespace(project=project)


def _service(tmp_path: Path, *, with_file: bool = True):
    root = tmp_path / "runtime"
    root.mkdir(parents=True, exist_ok=True)
    snapshot = _project_snapshot(tmp_path, with_file=with_file)
    projects = SimpleNamespace(
        read=lambda project_id: snapshot,
        project_root=lambda project_id: str(
            tmp_path / "projects" / project_id,
        ),
    )
    services = SimpleNamespace(root=root, projects=projects)
    service = SourceObservationService(services)
    return service


def test_window_below_minimum_is_rejected(tmp_path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ValidationError, match="too small"):
        asyncio.run(
            service.schedule_observe_clip(
                project_id="project-1",
                logical_asset_id="asset-1",
                start_ms=1000,
                end_ms=1000 + OBSERVE_MIN_WINDOW_MS - 1,
                question="发生了什么？",
                idempotency_key="call-1",
            ),
        )


def test_schedule_creates_task_and_worker_succeeds(
    tmp_path,
    monkeypatch,
) -> None:
    service = _service(tmp_path)
    # Register the project with the execution store's directory layout.
    created: list = []
    completed: list = []

    class FakeExecutions:
        def __init__(self) -> None:
            self.tasks: dict[str, SimpleNamespace] = {}

        def get_task(self, project_id, task_id):
            from services.runtime_files.errors import RecordNotFoundError

            if task_id not in self.tasks:
                raise RecordNotFoundError(task_id)
            return self.tasks[task_id]

        def create_task(self, candidate):
            record = SimpleNamespace(
                task_id=candidate.task_id,
                status=TaskStatus.QUEUED,
                kind=candidate.kind,
                metadata=dict(candidate.metadata),
                last_attempt_seq=0,
            )
            self.tasks[record.task_id] = record
            created.append(record)
            return record

        def append_attempt(self, project_id, task_id, **kwargs):
            record = self.tasks[task_id]
            if kwargs["status"].name == "RUNNING":
                record.status = TaskStatus.RUNNING
            else:
                record.status = TaskStatus(kwargs["status"].value)
                completed.append(kwargs)
            record.last_attempt_seq += 1
            return SimpleNamespace(**kwargs)

        def transition_task(self, *args, **kwargs):
            raise AssertionError("unexpected transition")

        def list_tasks(self, project_id):
            return []

    service.executions = FakeExecutions()
    monkeypatch.setattr(
        source_observation,
        "clip_segment_for_transport_sync",
        lambda local, out, start, end: out.write_bytes(b"clip") or out,
    )
    monkeypatch.setattr(
        source_observation.vlm_model,
        "multimodal_media_part",
        lambda uri, kind, fps: {
            "type": "video_url",
            "video_url": {"url": uri},
        },
    )

    async def fake_chat(content, **kwargs):
        return "00:01.000 出现了目标画面。"

    monkeypatch.setattr(
        source_observation.vlm_model,
        "chat_completion",
        fake_chat,
    )

    async def run() -> SimpleNamespace:
        task = await service.schedule_observe_clip(
            project_id="project-1",
            logical_asset_id="asset-1",
            start_ms=0,
            end_ms=5000,
            question="出现了什么？",
            idempotency_key="call-1",
        )
        worker = service._jobs.get(task.task_id)
        if worker is not None:
            await worker
        return task

    task = asyncio.run(run())
    assert created and created[0].kind is TaskKind.OBSERVE_SOURCE_CLIP
    assert completed and completed[0]["status"].name == "SUCCEEDED"
    output = completed[0]["output"]
    assert output["windowMs"] == [0, 5000]
    assert "目标画面" in output["answer"]
    # Replays converge on the durable record without a second task.
    replay = asyncio.run(
        service.schedule_observe_clip(
            project_id="project-1",
            logical_asset_id="asset-1",
            start_ms=0,
            end_ms=5000,
            question="出现了什么？",
            idempotency_key="call-1",
        ),
    )
    assert replay.task_id == task.task_id
    assert len(created) == 1


def test_worker_failure_marks_task_failed(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path)

    class FakeExecutions:
        def __init__(self) -> None:
            self.tasks: dict[str, SimpleNamespace] = {}
            self.failures: list = []

        def get_task(self, project_id, task_id):
            from services.runtime_files.errors import RecordNotFoundError

            if task_id not in self.tasks:
                raise RecordNotFoundError(task_id)
            return self.tasks[task_id]

        def create_task(self, candidate):
            record = SimpleNamespace(
                task_id=candidate.task_id,
                status=TaskStatus.QUEUED,
                kind=candidate.kind,
                metadata=dict(candidate.metadata),
                last_attempt_seq=0,
            )
            self.tasks[record.task_id] = record
            return record

        def append_attempt(self, project_id, task_id, **kwargs):
            record = self.tasks[task_id]
            if kwargs["status"].name == "RUNNING":
                record.status = TaskStatus.RUNNING
                record.last_attempt_seq += 1
            else:
                record.status = TaskStatus(kwargs["status"].value)
                if kwargs.get("error"):
                    self.failures.append(kwargs["error"])
            return SimpleNamespace(**kwargs)

        def transition_task(self, *args, **kwargs):
            return None

        def list_tasks(self, project_id):
            return []

    executions = FakeExecutions()
    service.executions = executions

    def failing_clip(*_args):
        raise RuntimeError("encode exploded")

    monkeypatch.setattr(
        source_observation,
        "clip_segment_for_transport_sync",
        failing_clip,
    )

    async def run() -> None:
        task = await service.schedule_observe_clip(
            project_id="project-1",
            logical_asset_id="asset-1",
            start_ms=0,
            end_ms=5000,
            question="出现了什么？",
            idempotency_key="call-1",
        )
        worker = service._jobs.get(task.task_id)
        if worker is not None:
            await worker

    asyncio.run(run())
    assert executions.failures
    assert executions.failures[0]["code"] == "OBSERVE_CLIP_FAILED"


# ── restart/shutdown lifecycle (review: orphaned RUNNING tasks) ───────────


class _LifecycleExecutions:
    """Durable-store fake that records terminal transitions."""

    def __init__(self) -> None:
        self.tasks: dict[str, SimpleNamespace] = {}
        self.failures: list = []

    def seed(self, task_id: str, status: TaskStatus) -> SimpleNamespace:
        record = SimpleNamespace(
            task_id=task_id,
            status=status,
            kind=TaskKind.OBSERVE_SOURCE_CLIP,
            metadata={
                "targetRef": "asset:asset-1",
                "assetVersionId": "version-1",
                "startMs": 0,
                "endMs": 5000,
                "question": "出现了什么？",
                "localPath": "clip.mp4",
            },
            last_attempt_seq=1 if status is TaskStatus.RUNNING else 0,
        )
        self.tasks[task_id] = record
        return record

    def get_task(self, project_id, task_id):
        from services.runtime_files.errors import RecordNotFoundError

        if task_id not in self.tasks:
            raise RecordNotFoundError(task_id)
        return self.tasks[task_id]

    def create_task(self, candidate):
        record = SimpleNamespace(
            task_id=candidate.task_id,
            status=TaskStatus.QUEUED,
            kind=candidate.kind,
            metadata=dict(candidate.metadata),
            last_attempt_seq=0,
        )
        self.tasks[record.task_id] = record
        return record

    def append_attempt(self, project_id, task_id, **kwargs):
        record = self.tasks[task_id]
        if kwargs["status"].name == "RUNNING":
            record.status = TaskStatus.RUNNING
            record.last_attempt_seq += 1
        else:
            record.status = TaskStatus(kwargs["status"].value)
            if kwargs.get("error"):
                self.failures.append(kwargs["error"])
        return SimpleNamespace(**kwargs)

    def transition_task(self, project_id, task_id, **kwargs):
        record = self.tasks[task_id]
        record.status = kwargs["status"]
        updates = kwargs.get("updates") or {}
        if updates.get("error"):
            self.failures.append(updates["error"])
        return record

    def list_tasks(self, project_id):
        return list(self.tasks.values())


def test_replay_fails_closed_on_an_orphaned_running_task(tmp_path) -> None:
    """The review's case: replay must not return a RUNNING record that no
    live worker owns — nothing would ever finish it."""

    service = _service(tmp_path)
    executions = _LifecycleExecutions()
    service.executions = executions
    task_id = source_observation._stable_id(
        "observe",
        "project-1",
        "call-1",
    )
    executions.seed(task_id, TaskStatus.RUNNING)

    replay = asyncio.run(
        service.schedule_observe_clip(
            project_id="project-1",
            logical_asset_id="asset-1",
            start_ms=0,
            end_ms=5000,
            question="出现了什么？",
            idempotency_key="call-1",
        ),
    )

    assert replay.status is TaskStatus.FAILED
    assert executions.failures
    assert "process restarted" in executions.failures[0]["message"]


def test_startup_recovery_terminalizes_orphaned_tasks(tmp_path) -> None:
    """Restart recovery fails QUEUED/RUNNING observation tasks closed."""

    service = _service(tmp_path)
    executions = _LifecycleExecutions()
    service.executions = executions
    executions.seed("task-running", TaskStatus.RUNNING)
    executions.seed("task-queued", TaskStatus.QUEUED)
    executions.seed("task-done", TaskStatus.SUCCEEDED)
    service.services.projects.discover_project_ids = lambda: ["project-1"]
    source_observation._SERVICES[str(service.services.root)] = service
    try:
        recovered = source_observation.recover_interrupted_source_observations(
            service.services,
        )
    finally:
        source_observation.clear_source_observation_service_registry()

    assert recovered == 2
    assert executions.tasks["task-running"].status is TaskStatus.FAILED
    assert executions.tasks["task-queued"].status is TaskStatus.FAILED
    assert executions.tasks["task-done"].status is TaskStatus.SUCCEEDED
    assert all(
        "process restart" in failure["message"]
        for failure in executions.failures
    )


def test_drain_terminalizes_inflight_tasks(tmp_path, monkeypatch) -> None:
    """Shutdown cancels the worker and fails its Task closed."""

    service = _service(tmp_path)
    executions = _LifecycleExecutions()
    service.executions = executions
    monkeypatch.setattr(
        source_observation,
        "clip_segment_for_transport_sync",
        lambda local, out, start, end: out.write_bytes(b"clip") or out,
    )
    monkeypatch.setattr(
        source_observation.vlm_model,
        "multimodal_media_part",
        lambda uri, kind, fps: {"type": "video_url"},
    )

    async def never_returns(content, **kwargs):
        await asyncio.sleep(300)

    monkeypatch.setattr(
        source_observation.vlm_model,
        "chat_completion",
        never_returns,
    )

    async def run() -> SimpleNamespace:
        task = await service.schedule_observe_clip(
            project_id="project-1",
            logical_asset_id="asset-1",
            start_ms=0,
            end_ms=5000,
            question="出现了什么？",
            idempotency_key="call-drain",
        )
        # Let the worker reach RUNNING before shutting down.
        for _ in range(50):
            await asyncio.sleep(0)
            if executions.tasks[task.task_id].status is TaskStatus.RUNNING:
                break
        await service.drain()
        return executions.tasks[task.task_id]

    record = asyncio.run(run())

    assert record.status is TaskStatus.FAILED
    assert not service._jobs
    assert executions.failures
    assert "shutdown" in executions.failures[0]["message"]
