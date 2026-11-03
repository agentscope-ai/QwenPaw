# -*- coding: utf-8 -*-
# flake8: noqa: E501
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


def _service(tmp_path: Path):
    media = tmp_path / "projects" / "project-1" / "assets" / "clip.mp4"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"\x00" * 32)
    source = SimpleNamespace(
        logical_asset_id="asset-1",
        selected_asset_version_id="version-1",
    )
    version = SimpleNamespace(version_id="version-1", file_id="file-1")
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
    snapshot = SimpleNamespace(project=project)
    root = tmp_path / "runtime"
    root.mkdir(parents=True, exist_ok=True)
    projects = SimpleNamespace(
        read=lambda project_id: snapshot,
        project_root=lambda project_id: str(
            tmp_path / "projects" / project_id,
        ),
    )
    services = SimpleNamespace(root=root, projects=projects)
    return SourceObservationService(services)


class _Executions:
    def __init__(self) -> None:
        self.tasks: dict[str, SimpleNamespace] = {}
        self.created: list = []
        self.completed: list = []
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
        self.created.append(record)
        return record

    def append_attempt(self, project_id, task_id, **kwargs):
        record = self.tasks[task_id]
        if kwargs["status"].name == "RUNNING":
            record.status = TaskStatus.RUNNING
            record.last_attempt_seq += 1
        else:
            record.status = TaskStatus(kwargs["status"].value)
            self.completed.append(kwargs)
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


def _schedule(service, *, end_ms: int = 5000, idempotency_key: str = "call-1"):
    return service.schedule_observe_clip(
        project_id="project-1",
        logical_asset_id="asset-1",
        start_ms=0,
        end_ms=end_ms,
        question="出现了什么？",
        idempotency_key=idempotency_key,
    )


async def _schedule_and_await(service, **kwargs) -> SimpleNamespace:
    task = await _schedule(service, **kwargs)
    worker = service._jobs.get(task.task_id)
    if worker is not None:
        await worker
    return task


def test_window_below_minimum_is_rejected(tmp_path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ValidationError, match="too small"):
        asyncio.run(_schedule(service, end_ms=OBSERVE_MIN_WINDOW_MS - 1))


def test_schedule_creates_task_and_worker_succeeds(
    tmp_path,
    monkeypatch,
) -> None:
    service = _service(tmp_path)
    executions = _Executions()
    service.executions = executions
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

    task = asyncio.run(_schedule_and_await(service))
    assert executions.created
    assert executions.created[0].kind is TaskKind.OBSERVE_SOURCE_CLIP
    assert executions.completed
    assert executions.completed[0]["status"].name == "SUCCEEDED"
    output = executions.completed[0]["output"]
    assert output["windowMs"] == [0, 5000]
    assert "目标画面" in output["answer"]
    replay = asyncio.run(_schedule(service))
    assert replay.task_id == task.task_id
    assert len(executions.created) == 1


def test_worker_failure_marks_task_failed(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path)
    executions = _Executions()
    service.executions = executions

    def failing_clip(*_args):
        raise RuntimeError("encode exploded")

    monkeypatch.setattr(
        source_observation,
        "clip_segment_for_transport_sync",
        failing_clip,
    )

    asyncio.run(_schedule_and_await(service))
    assert executions.failures
    assert executions.failures[0]["code"] == "OBSERVE_CLIP_FAILED"


def test_replay_fails_closed_on_an_orphaned_running_task(tmp_path) -> None:
    # Replay must not return a RUNNING record that no live worker owns.
    service = _service(tmp_path)
    executions = _Executions()
    service.executions = executions
    task_id = source_observation._stable_id("observe", "project-1", "call-1")
    executions.seed(task_id, TaskStatus.RUNNING)

    replay = asyncio.run(_schedule(service))

    assert replay.status is TaskStatus.FAILED
    assert executions.failures
    assert "process restarted" in executions.failures[0]["message"]


def test_startup_recovery_terminalizes_orphaned_tasks(tmp_path) -> None:
    service = _service(tmp_path)
    executions = _Executions()
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
