# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Tests for services.media.source_video_reader (read_source_video)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from domain.enums import TaskKind, TaskStatus
from services.media import source_video_reader
from services.media.source_video_reader import (
    MIN_FRAMES,
    SourceVideoReaderService,
    _plan_timestamps,
    _uniform_downsample,
    read_video_frames_sync,
    resolve_video_frame_ref,
    video_frame_path,
    video_frame_ref,
)

# ── three-stage math ─────────────────────────────────────────────────────────


def test_plan_timestamps_spans_the_window() -> None:
    stamps = _plan_timestamps(
        duration=100.0,
        native_fps=25.0,
        start_sec=10.0,
        end_sec=20.0,
        nframes=5,
    )
    assert stamps[0] == 10.0
    assert stamps[-1] == pytest.approx(20.0)
    diffs = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(d == pytest.approx(diffs[0]) for d in diffs)


def test_uniform_downsample_converges_to_budget() -> None:
    frames = [(float(i), b"x" * 1000) for i in range(20)]
    kept = _uniform_downsample(frames, 5000)
    assert MIN_FRAMES <= len(kept) <= 5
    # First/last coverage is preserved by uniform index mapping.
    assert kept[0][0] == 0.0
    assert kept[-1][0] == 19.0


def _fake_extraction_env(monkeypatch, *, duration=100.0, frame_bytes=1000):
    monkeypatch.setattr(
        source_video_reader,
        "_require_ffmpeg_pair",
        lambda: ("ffmpeg", "ffprobe"),
    )
    monkeypatch.setattr(
        source_video_reader,
        "get_video_info",
        lambda ffprobe, path: {
            "width": 1920,
            "height": 1080,
            "duration": duration,
            "native_fps": 25.0,
        },
    )

    calls: list[list[float]] = []

    def fake_extract(ffmpeg, path, timestamps, h, w, max_workers=16):
        calls.append(list(timestamps))
        return [(round(ts, 1), b"j" * frame_bytes) for ts in timestamps]

    monkeypatch.setattr(
        source_video_reader,
        "extract_frames_by_seeking",
        fake_extract,
    )
    monkeypatch.setattr(
        source_video_reader.model_config,
        "get_vlm_max_inline_bytes",
        lambda: 10 * 1024 * 1024,
    )
    return calls


def test_three_stage_auto_fps(monkeypatch, tmp_path) -> None:
    calls = _fake_extraction_env(monkeypatch, duration=100.0)
    result = read_video_frames_sync(tmp_path / "in.mp4", max_frames=32)
    # Stage 1: 100s * 2fps = 200 capped at 32; stage 2 probe (1 call) then
    # stage 3 extraction (1 call).
    assert len(calls) == 2
    assert len(calls[0]) == 1  # mid-window probe
    assert len(result["frames"]) == 32
    # 32px-aligned resolution from the budget math.
    assert result["target_h"] % 32 == 0
    assert result["target_w"] % 32 == 0


def test_stage2_precaps_frame_count_by_bytes(monkeypatch, tmp_path) -> None:
    _fake_extraction_env(monkeypatch, duration=100.0, frame_bytes=600_000)
    monkeypatch.setattr(
        source_video_reader.model_config,
        "get_vlm_max_inline_bytes",
        lambda: 3_000_000,
    )
    result = read_video_frames_sync(tmp_path / "in.mp4", max_frames=32)
    # 3MB budget / 600KB per frame = 5 frames max.
    assert len(result["frames"]) <= 5


# ── frame refs ───────────────────────────────────────────────────────────────


def test_video_frame_ref_roundtrip(tmp_path) -> None:
    ref = video_frame_ref("version-abc", 12_345)
    resolved = resolve_video_frame_ref(tmp_path, ref)
    assert resolved is not None
    version_id, ts_ms, path = resolved
    assert version_id == "version-abc"
    assert ts_ms == 12_345
    assert path == video_frame_path(tmp_path, "version-abc", 12_345)


# ── task scheduling ──────────────────────────────────────────────────────────


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
    return SourceVideoReaderService(services)


class _FakeExecutions:
    def __init__(self) -> None:
        self.tasks: dict[str, SimpleNamespace] = {}
        self.succeeded: list = []

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
        record.last_attempt_seq += 1
        return SimpleNamespace(**kwargs)

    def transition_task(self, *args, **kwargs):
        return None

    def list_tasks(self, project_id):
        return []


def test_schedule_persists_frames_and_refs(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path)
    service.executions = _FakeExecutions()
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
        task = await service.schedule_read_source_video(
            project_id="project-1",
            logical_asset_id="asset-1",
            idempotency_key="call-1",
        )
        worker = service._jobs.get(task.task_id)
        if worker is not None:
            await worker
        return task

    task = asyncio.run(run())
    assert service.executions.tasks[task.task_id].kind is (
        TaskKind.READ_SOURCE_VIDEO
    )
    output = service.executions.succeeded[0]
    assert output["frameCount"] == 2
    refs = output["frameImageRefs"]
    assert refs[0]["ref"] == video_frame_ref("version-1", 0)
    assert refs[1]["ref"] == video_frame_ref("version-1", 5000)
    # Frames are durable Runtime files resolvable through the ref.
    project_root = tmp_path / "projects" / "project-1"
    resolved = resolve_video_frame_ref(project_root, refs[1]["ref"])
    assert resolved is not None and resolved[2].read_bytes() == b"frame1"
    # Replays converge on the durable record.
    replay = asyncio.run(
        service.schedule_read_source_video(
            project_id="project-1",
            logical_asset_id="asset-1",
            idempotency_key="call-1",
        ),
    )
    assert replay.task_id == task.task_id


# ── restart/shutdown lifecycle (review: orphaned RUNNING tasks) ───────────


class _LifecycleExecutions(_FakeExecutions):
    """Extends the fake with failure capture and seeded records."""

    def __init__(self) -> None:
        super().__init__()
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

    def append_attempt(self, project_id, task_id, **kwargs):
        if kwargs["status"].name != "RUNNING" and kwargs.get("error"):
            self.failures.append(kwargs["error"])
        return super().append_attempt(project_id, task_id, **kwargs)

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
    task_id = source_video_reader._stable_id(
        "readvideo",
        "project-1",
        "call-1",
    )
    executions.seed(task_id, TaskStatus.RUNNING)

    replay = asyncio.run(
        service.schedule_read_source_video(
            project_id="project-1",
            logical_asset_id="asset-1",
            idempotency_key="call-1",
        ),
    )

    assert replay.status is TaskStatus.FAILED
    assert executions.failures
    assert "process restarted" in executions.failures[0]["message"]


def test_startup_recovery_terminalizes_orphaned_tasks(tmp_path) -> None:
    """Restart recovery fails QUEUED/RUNNING read tasks closed."""

    service = _service(tmp_path)
    executions = _LifecycleExecutions()
    service.executions = executions
    executions.seed("task-running", TaskStatus.RUNNING)
    executions.seed("task-queued", TaskStatus.QUEUED)
    executions.seed("task-done", TaskStatus.SUCCEEDED)
    service.services.projects.discover_project_ids = lambda: ["project-1"]
    source_video_reader._SERVICES[str(service.services.root)] = service
    try:
        recovered = source_video_reader.recover_interrupted_source_video_reads(
            service.services,
        )
    finally:
        source_video_reader.clear_source_video_reader_service_registry()

    assert recovered == 2
    assert executions.tasks["task-running"].status is TaskStatus.FAILED
    assert executions.tasks["task-queued"].status is TaskStatus.FAILED
    assert executions.tasks["task-done"].status is TaskStatus.SUCCEEDED
    assert all(
        "process restart" in failure["message"]
        for failure in executions.failures
    )
