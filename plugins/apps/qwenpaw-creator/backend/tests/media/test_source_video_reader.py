# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Tests for services.media.source_video_reader (read_source_video)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace


from domain.enums import TaskKind, TaskStatus
from services.media import source_video_reader
from services.media.source_video_reader import (
    MIN_FRAMES,
    SourceVideoReaderService,
    _uniform_downsample,
    resolve_video_frame_ref,
    video_frame_ref,
)


def test_uniform_downsample_converges_to_budget() -> None:
    frames = [(float(i), b"x" * 1000) for i in range(20)]
    kept = _uniform_downsample(frames, 5000)
    assert MIN_FRAMES <= len(kept) <= 5
    # First/last coverage is preserved by uniform index mapping.
    assert kept[0][0] == 0.0
    assert kept[-1][0] == 19.0


def _service(tmp_path: Path):
    media = tmp_path / "projects" / "project-1" / "assets" / "clip.mp4"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"\x00" * 32)
    source = SimpleNamespace(
        logical_asset_id="asset-1",
        selected_asset_version_id="version-1",
    )
    project = SimpleNamespace(
        sources=SimpleNamespace(
            sources=SimpleNamespace(items={"source-1": source}),
        ),
        assets=SimpleNamespace(
            source_versions_by_id={
                "version-1": SimpleNamespace(
                    version_id="version-1",
                    file_id="file-1",
                ),
            },
            files_by_id={
                "file-1": SimpleNamespace(relative_uri="assets/clip.mp4"),
            },
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
    return SourceVideoReaderService(services)


class _Executions:
    def __init__(self) -> None:
        self.tasks: dict[str, SimpleNamespace] = {}
        self.succeeded: list = []
        self.failures: list = []

    def seed(self, task_id: str, status: TaskStatus) -> SimpleNamespace:
        record = SimpleNamespace(
            task_id=task_id,
            status=status,
            kind=TaskKind.READ_SOURCE_VIDEO,
            metadata={
                "targetRef": "asset:asset-1",
                "assetVersionId": "version-1",
                "budget": "normal",
                "fps": 0,
                "startMs": None,
                "endMs": None,
                "maxFrames": 16,
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
        else:
            record.status = TaskStatus(kwargs["status"].value)
            if kwargs.get("output"):
                self.succeeded.append(kwargs["output"])
            if kwargs.get("error"):
                self.failures.append(kwargs["error"])
        record.last_attempt_seq += 1
        return SimpleNamespace(**kwargs)

    def transition_task(self, project_id, task_id, **kwargs):
        record = self.tasks[task_id]
        record.status = kwargs["status"]
        updates = kwargs.get("updates") or {}
        if updates.get("error"):
            self.failures.append(updates["error"])
        return record


def _schedule(service):
    return service.schedule_read_source_video(
        project_id="project-1",
        logical_asset_id="asset-1",
        idempotency_key="call-1",
    )


def test_schedule_persists_frames_and_refs(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path)
    service.executions = _Executions()
    monkeypatch.setattr(
        source_video_reader,
        "read_video_frames_sync",
        lambda path, **kwargs: {
            "frames": [(0.0, b"frame0"), (5.0, b"frame1")],
            "duration": 10.0,
            "fps_used": 0.2,
            "target_h": 288,
            "target_w": 512,
        },
    )

    async def run():
        task = await _schedule(service)
        worker = service._jobs.get(task.task_id)
        if worker is not None:
            await worker
        return task

    task = asyncio.run(run())
    assert (
        service.executions.tasks[task.task_id].kind
        is TaskKind.READ_SOURCE_VIDEO
    )
    output = service.executions.succeeded[0]
    assert output["frameCount"] == 2
    refs = output["frameImageRefs"]
    assert refs[0]["ref"] == video_frame_ref("version-1", 0)
    assert refs[1]["ref"] == video_frame_ref("version-1", 5000)
    project_root = tmp_path / "projects" / "project-1"
    resolved = resolve_video_frame_ref(project_root, refs[1]["ref"])
    assert resolved is not None and resolved[2].read_bytes() == b"frame1"
    replay = asyncio.run(_schedule(service))
    assert replay.task_id == task.task_id


def test_replay_fails_closed_on_an_orphaned_running_task(tmp_path) -> None:
    # Replay must not return a RUNNING record that no live worker owns.
    service = _service(tmp_path)
    executions = _Executions()
    service.executions = executions
    task_id = source_video_reader._stable_id(
        "readvideo",
        "project-1",
        "call-1",
    )
    executions.seed(task_id, TaskStatus.RUNNING)

    replay = asyncio.run(_schedule(service))

    assert replay.status is TaskStatus.FAILED
    assert executions.failures
    assert "process restarted" in executions.failures[0]["message"]
