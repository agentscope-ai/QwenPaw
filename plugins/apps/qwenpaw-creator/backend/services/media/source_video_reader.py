# -*- coding: utf-8 -*-
"""Coarse-to-fine on-demand video reading (先粗看再细看).

Ports the upstream ``read_video`` three-stage adaptive sampler as a
Creator specialist tool: ① dynamic FPS picks a frame count for the
requested window, ② a mid-window probe frame measures per-frame bytes
and pre-caps the count against the response budget, ③ frames are
extracted by parallel keyframe seeking and uniformly down-sampled if the
total still exceeds the budget. Frames land as Runtime files
(``runtime/video-frames/``) and enter the specialist's context as native
images through the same injection mechanism as ``read_document`` page
images.

Runs as a ProjectExecutionStore task (``TaskKind.READ_SOURCE_VIDEO``) so
the tool declares ``wait=TASK`` and the driver awaits the durable record.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from domain.enums import TaskKind, TaskStatus
from domain.errors import ValidationError
from models import config as model_config
from services.media.source_observation import resolve_local_source_media
from services.runtime_files.errors import RecordNotFoundError
from services.runtime_files.execution_models import (
    TaskAttemptStatus,
    TaskRecord,
)
from services.runtime_files.execution_store import (
    ExecutionStateConflict,
    ProjectExecutionStore,
)
from services.runtime_files.runtime_dependencies import (
    resolve_ffmpeg,
    resolve_ffprobe,
)
from vendor.media_toolkit.image_budget import (
    VIDEO_BUDGET_TOKENS,
    VIDEO_MIN_PIXELS,
    budget_to_pixels,
    smart_resize,
)
from vendor.media_toolkit.video_read import (
    DEFAULT_FPS,
    compute_dynamic_fps,
    extract_frames_by_seeking,
    format_timestamp,
    get_video_info,
)

logger = logging.getLogger("creator.source_video_reader")

MIN_FRAMES = 2
# Context ceiling: every frame becomes one native image part in the
# specialist's next message, so the cap is far below the upstream MCP
# default of 600.
HARD_MAX_FRAMES = 64
DEFAULT_MAX_FRAMES = 32
# Rough base64 bytes per pixel, used when the probe sampling fails
# (upstream B64_BYTES_PER_PIXEL).
BYTES_PER_PIXEL_ESTIMATE = 0.35
# Response budget: the upstream 15 MiB tool-response cap, additionally
# bounded by the active VLM inline transport limit.
UPSTREAM_RESPONSE_BYTES = 15 * 1024 * 1024

VALID_BUDGETS = ("small", "normal", "large")


def _response_budget_bytes() -> int:
    return min(
        UPSTREAM_RESPONSE_BYTES,
        model_config.get_vlm_max_inline_bytes(),
    )


def _require_ffmpeg_pair() -> tuple[str, str]:
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg is required for read_source_video; set "
            "CREATOR_FFMPEG_PATH, install ffmpeg, or install imageio-ffmpeg",
        )
    # Naive string surgery on the ffmpeg path breaks for Homebrew Cellar
    # layouts (the version directory also contains "ffmpeg"); use the
    # shared resolver which probes PATH and the paired sibling correctly.
    ffprobe = resolve_ffprobe(ffmpeg_path=ffmpeg)
    if not ffprobe:
        raise RuntimeError(
            "ffprobe is required for read_source_video; set "
            "CREATOR_FFPROBE_PATH or install ffmpeg's ffprobe",
        )
    return ffmpeg, ffprobe


def video_frame_ref(version_id: str, ts_ms: int) -> str:
    """Stable evidence ref for one extracted source frame."""
    return f"video-frame://{version_id}/{ts_ms}"


def video_frames_dir(project_root: Path, version_id: str) -> Path:
    return project_root / "runtime" / "video-frames" / version_id[:24]


def video_frame_path(
    project_root: Path,
    version_id: str,
    ts_ms: int,
) -> Path:
    return video_frames_dir(project_root, version_id) / f"frame-{ts_ms}.jpg"


def resolve_video_frame_ref(
    project_root: Path,
    ref: str,
) -> tuple[str, int, Path] | None:
    """Parse a video-frame:// ref into (versionId, tsMs, local path)."""
    text = str(ref or "").strip()
    if not text.startswith("video-frame://"):
        return None
    remainder = text.removeprefix("video-frame://")
    version_id, _, ts_text = remainder.partition("/")
    if not version_id or not ts_text.isdigit():
        return None
    ts_ms = int(ts_text)
    return version_id, ts_ms, video_frame_path(project_root, version_id, ts_ms)


def _stable_id(prefix: str, project_id: str, key: str) -> str:
    return (
        f"{prefix}-"
        + uuid5(
            NAMESPACE_URL,
            f"qwenpaw-creator:source-video-reader:{prefix}:"
            f"{project_id}:{key}",
        ).hex
    )


@dataclass(frozen=True, slots=True)
class SourceVideoReadJob:
    project_id: str
    task_id: str
    logical_asset_id: str
    version_id: str
    local_path: str
    fps: float
    budget: str
    start_ms: int | None
    end_ms: int | None
    max_frames: int


def _plan_timestamps(
    *,
    duration: float,
    native_fps: float,
    start_sec: float,
    end_sec: float | None,
    nframes: int,
) -> list[float]:
    """First frame at the window start, last at its end (upstream layout)."""
    seg_end = end_sec if end_sec is not None else duration
    seek_end = min(seg_end, duration - 1.0 / native_fps)
    span = seek_end - start_sec
    if nframes <= 1 or span <= 0:
        return [start_sec]
    step = span / (nframes - 1)
    return [start_sec + index * step for index in range(nframes)]


def _uniform_downsample(
    frames: list[tuple[float, bytes]],
    budget: int,
) -> list[tuple[float, bytes]]:
    total = sum(len(data) for _, data in frames)
    while total > budget and len(frames) > MIN_FRAMES:
        keep = max(MIN_FRAMES, int(len(frames) * budget / total))
        if keep >= len(frames):
            keep = len(frames) - 1
        step = (len(frames) - 1) / (keep - 1) if keep > 1 else 0
        frames = [frames[round(index * step)] for index in range(keep)]
        total = sum(len(data) for _, data in frames)
    return frames


def read_video_frames_sync(
    local_path: Path,
    *,
    fps: float = 0,
    budget: str = "normal",
    start_ms: int | None = None,
    end_ms: int | None = None,
    max_frames: int = DEFAULT_MAX_FRAMES,
) -> dict[str, Any]:
    """Three-stage adaptive frame extraction (upstream read_video handle).

    Returns ``{"frames": [(ts_sec, jpeg_bytes)], "duration": float,
    "fps_used": float, "target_h": int, "target_w": int}``.
    """
    ffmpeg, ffprobe = _require_ffmpeg_pair()
    info = get_video_info(ffprobe, str(local_path))
    duration = info["duration"]
    if duration <= 0:
        raise ValidationError("cannot determine video duration")

    start_sec = (start_ms or 0) / 1000.0
    end_sec = end_ms / 1000.0 if end_ms is not None else None
    start_sec = max(start_sec, 0.0)
    if start_sec >= duration:
        raise ValidationError(
            f"startMs ({int(start_sec * 1000)}) is beyond the video "
            f"duration ({duration:.1f}s)",
        )
    if end_sec is not None:
        if end_sec <= start_sec:
            raise ValidationError("endMs must be greater than startMs")
        end_sec = min(end_sec, duration)
    segment_duration = (end_sec if end_sec is not None else duration) - (
        start_sec
    )

    max_frames = max(MIN_FRAMES, min(int(max_frames), HARD_MAX_FRAMES))
    max_pixels = budget_to_pixels(budget, VIDEO_BUDGET_TOKENS)
    target_h, target_w = smart_resize(
        info["height"],
        info["width"],
        VIDEO_MIN_PIXELS,
        max_pixels,
    )

    # ── Stage 1: target count from requested or auto-selected FPS ──────
    if fps > 0:
        fps_used = min(fps, info["native_fps"])
        nframes = int(segment_duration * fps_used)
        nframes = max(MIN_FRAMES, min(max_frames, nframes))
    else:
        fps_used, nframes = compute_dynamic_fps(
            segment_duration,
            info["native_fps"],
            MIN_FRAMES,
            max_frames,
            DEFAULT_FPS,
        )

    # ── Stage 2: probe one mid-window frame to pre-cap the count ───────
    response_budget = _response_budget_bytes()
    sample = extract_frames_by_seeking(
        ffmpeg,
        str(local_path),
        [start_sec + segment_duration * 0.5],
        target_h,
        target_w,
    )
    bytes_per_frame = (
        len(sample[0][1])
        if sample
        else int(target_h * target_w * BYTES_PER_PIXEL_ESTIMATE)
    )
    max_safe_frames = max(MIN_FRAMES, response_budget // bytes_per_frame)
    nframes = min(nframes, max_safe_frames)

    # ── Stage 3: extract; uniformly downsample when over budget ────────
    timestamps = _plan_timestamps(
        duration=duration,
        native_fps=info["native_fps"],
        start_sec=start_sec,
        end_sec=end_sec,
        nframes=nframes,
    )
    frames = extract_frames_by_seeking(
        ffmpeg,
        str(local_path),
        timestamps,
        target_h,
        target_w,
    )
    if not frames:
        raise RuntimeError("frame extraction produced no frames")
    frames = _uniform_downsample(frames, response_budget)

    fps_used = (
        len(frames) / segment_duration if segment_duration > 0 else fps_used
    )
    return {
        "frames": frames,
        "duration": duration,
        "fps_used": fps_used,
        "target_h": target_h,
        "target_w": target_w,
    }


class SourceVideoReaderService:
    """Owns read-source-video task scheduling for one runtime root."""

    def __init__(self, services: Any) -> None:
        self.services = services
        self.executions = ProjectExecutionStore(services.root)
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._job_specs: dict[str, SourceVideoReadJob] = {}

    async def schedule_read_source_video(
        self,
        *,
        project_id: str,
        logical_asset_id: str,
        fps: float = 0,
        budget: str = "normal",
        start_ms: int | None = None,
        end_ms: int | None = None,
        max_frames: int = DEFAULT_MAX_FRAMES,
        idempotency_key: str,
        caused_by_request_id: str | None = None,
    ) -> TaskRecord:
        if budget not in VALID_BUDGETS:
            raise ValidationError(
                f"budget must be one of {'/'.join(VALID_BUDGETS)}",
            )
        if fps < 0:
            raise ValidationError("fps must be >= 0 (0 = auto)")
        if start_ms is not None and start_ms < 0:
            raise ValidationError("startMs must be >= 0")
        if start_ms is not None and end_ms is not None and end_ms <= start_ms:
            raise ValidationError("endMs must be greater than startMs")
        version_id, local_path = await asyncio.to_thread(
            resolve_local_source_media,
            self.services,
            self.executions,
            project_id,
            logical_asset_id,
        )
        task = await asyncio.to_thread(
            self._admit_sync,
            project_id,
            logical_asset_id,
            version_id,
            local_path,
            fps,
            budget,
            start_ms,
            end_ms,
            max_frames,
            idempotency_key,
            caused_by_request_id,
        )
        job = SourceVideoReadJob(
            project_id=project_id,
            task_id=task.task_id,
            logical_asset_id=logical_asset_id,
            version_id=version_id,
            local_path=str(local_path),
            fps=fps,
            budget=budget,
            start_ms=start_ms,
            end_ms=end_ms,
            max_frames=max_frames,
        )
        if task.status is TaskStatus.QUEUED:
            self._spawn(job)
        elif task.status is TaskStatus.RUNNING and not self._has_live_worker(
            task.task_id,
        ):
            # Idempotent replay found an orphan: a RUNNING record whose
            # in-memory worker died with a previous process. Nothing will
            # ever finish it, so fail it closed (retryable) instead of
            # silently returning a Task the caller would await forever.
            await asyncio.to_thread(
                self._fail_sync,
                job,
                RuntimeError(
                    "video read worker was lost (process restarted); "
                    "retry the read",
                ),
            )
            task = await asyncio.to_thread(
                self.executions.get_task,
                project_id,
                task.task_id,
            )
        return task

    def _has_live_worker(self, task_id: str) -> bool:
        worker = self._jobs.get(task_id)
        return worker is not None and not worker.done()

    async def drain(self) -> None:
        """Cancel in-flight workers and fail their Tasks closed (retryable).

        Frame extraction lives entirely in memory and scratch space, so
        shutdown must terminalize the owning Task instead of leaving it
        RUNNING for waiters that poll it after restart.
        """

        specs = dict(self._job_specs)
        workers = {
            task_id: worker
            for task_id, worker in self._jobs.items()
            if not worker.done()
        }
        self._jobs.clear()
        self._job_specs.clear()
        for worker in workers.values():
            worker.cancel()
        if workers:
            await asyncio.gather(*workers.values(), return_exceptions=True)
        for task_id in workers:
            job = specs.get(task_id)
            if job is None:
                continue
            await asyncio.to_thread(
                self._fail_sync,
                job,
                RuntimeError(
                    "video read was interrupted by shutdown; retry the read",
                ),
            )

    def _admit_sync(  # pylint: disable=too-many-arguments
        self,
        project_id: str,
        logical_asset_id: str,
        version_id: str,
        local_path: Path,
        fps: float,
        budget: str,
        start_ms: int | None,
        end_ms: int | None,
        max_frames: int,
        idempotency_key: str,
        caused_by_request_id: str | None,
    ) -> TaskRecord:
        task_id = _stable_id("readvideo", project_id, idempotency_key)
        try:
            existing = self.executions.get_task(project_id, task_id)
        except RecordNotFoundError:
            existing = None
        if existing is not None:
            return existing
        target_ref = f"asset:{logical_asset_id}"
        candidate = TaskRecord(
            task_id=task_id,
            project_id=project_id,
            kind=TaskKind.READ_SOURCE_VIDEO,
            request_fingerprint=uuid5(
                NAMESPACE_URL,
                "read-source-video:"
                f"{version_id}:{fps}:{budget}:{start_ms}:{end_ms}:"
                f"{max_frames}",
            ).hex,
            idempotency_key=task_id,
            input_refs=[target_ref],
            caused_by_request_id=caused_by_request_id,
            metadata={
                "targetRef": target_ref,
                "assetVersionId": version_id,
                "budget": budget,
                "fps": fps,
                "startMs": start_ms,
                "endMs": end_ms,
                "maxFrames": max_frames,
                "localPath": str(local_path),
            },
        )
        return self.executions.create_task(candidate)

    def _spawn(self, job: SourceVideoReadJob) -> None:
        current = self._jobs.get(job.task_id)
        if current is not None and not current.done():
            return
        worker = asyncio.create_task(
            self._drive(job),
            name=f"read-source-video:{job.task_id}",
        )
        self._jobs[job.task_id] = worker
        self._job_specs[job.task_id] = job

        def discard(done: asyncio.Task[None]) -> None:
            if self._jobs.get(job.task_id) is done:
                self._jobs.pop(job.task_id, None)
                self._job_specs.pop(job.task_id, None)
            if not done.cancelled():
                try:
                    done.exception()
                except BaseException:  # pylint: disable=broad-except
                    pass

        worker.add_done_callback(discard)

    async def _drive(self, job: SourceVideoReadJob) -> None:
        try:
            await self._execute(job)
        except asyncio.CancelledError:  # pylint: disable=try-except-raise
            raise
        except Exception as error:  # pylint: disable=broad-except
            logger.exception(
                "read source video failed: project=%s task=%s",
                job.project_id,
                job.task_id,
            )
            await asyncio.to_thread(self._fail_sync, job, error)

    async def _execute(self, job: SourceVideoReadJob) -> None:
        task = await asyncio.to_thread(
            self.executions.get_task,
            job.project_id,
            job.task_id,
        )
        if task.status is not TaskStatus.QUEUED:
            return
        attempt_id = f"{job.task_id}-a{task.last_attempt_seq + 1}"
        await asyncio.to_thread(
            self.executions.append_attempt,
            job.project_id,
            job.task_id,
            event_id=f"{attempt_id}-running",
            attempt_id=attempt_id,
            status=TaskAttemptStatus.RUNNING,
            input={
                "assetVersionId": job.version_id,
                "budget": job.budget,
                "startMs": job.start_ms,
                "endMs": job.end_ms,
            },
        )
        local_path = Path(job.local_path)
        if not local_path.is_file():
            raise RuntimeError(
                f"source media is no longer available: {local_path}",
            )
        extraction = await asyncio.to_thread(
            read_video_frames_sync,
            local_path,
            fps=job.fps,
            budget=job.budget,
            start_ms=job.start_ms,
            end_ms=job.end_ms,
            max_frames=job.max_frames,
        )
        output = await asyncio.to_thread(self._persist_frames, job, extraction)
        await asyncio.to_thread(
            self.executions.append_attempt,
            job.project_id,
            job.task_id,
            event_id=f"{attempt_id}-succeeded",
            attempt_id=attempt_id,
            status=TaskAttemptStatus.SUCCEEDED,
            output=output,
        )

    def _persist_frames(
        self,
        job: SourceVideoReadJob,
        extraction: dict[str, Any],
    ) -> dict[str, Any]:
        project_root = Path(
            self.services.projects.project_root(job.project_id),
        )
        frames_root = video_frames_dir(project_root, job.version_id)
        frames_root.mkdir(parents=True, exist_ok=True)
        duration = float(extraction["duration"])
        entries: list[dict[str, Any]] = []
        for ts_sec, data in extraction["frames"]:
            ts_ms = round(float(ts_sec) * 1000)
            path = video_frame_path(project_root, job.version_id, ts_ms)
            path.write_bytes(data)
            entries.append(
                {
                    "tsMs": ts_ms,
                    "label": format_timestamp(float(ts_sec), duration),
                    "ref": video_frame_ref(job.version_id, ts_ms),
                },
            )
        summary = (
            f"素材 {job.logical_asset_id}（{duration:.1f}s）按 "
            f"budget={job.budget} 抽取 {len(entries)} 帧 @ "
            f"{extraction['fps_used']:.2f}fps，分辨率 "
            f"{extraction['target_h']}x{extraction['target_w']} (HxW)，"
            f"覆盖 {entries[0]['label']}–{entries[-1]['label']}。"
            "帧图随下一条消息以原生图片进入你的上下文。"
        )
        return {
            "ok": True,
            "assetId": job.logical_asset_id,
            "versionId": job.version_id,
            "durationMs": round(duration * 1000),
            "frameCount": len(entries),
            "fpsUsed": round(float(extraction["fps_used"]), 3),
            "resolution": (
                f"{extraction['target_h']}x{extraction['target_w']}"
            ),
            "frameImageRefs": entries,
            "summary": summary,
        }

    def _fail_sync(
        self,
        job: SourceVideoReadJob,
        error: Exception,
    ) -> None:
        try:
            task = self.executions.get_task(job.project_id, job.task_id)
            if task.status is TaskStatus.RUNNING:
                attempt_id = f"{job.task_id}-a{task.last_attempt_seq}"
                self.executions.append_attempt(
                    job.project_id,
                    job.task_id,
                    event_id=f"{attempt_id}-failed",
                    attempt_id=attempt_id,
                    status=TaskAttemptStatus.FAILED,
                    error={
                        "code": "READ_SOURCE_VIDEO_FAILED",
                        "message": str(error)[:2000],
                    },
                )
            elif task.status is TaskStatus.QUEUED:
                self.executions.transition_task(
                    job.project_id,
                    job.task_id,
                    expected_status=TaskStatus.QUEUED,
                    status=TaskStatus.FAILED,
                    updates={
                        "error": {
                            "code": "READ_SOURCE_VIDEO_FAILED",
                            "message": str(error)[:2000],
                        },
                    },
                )
        except (ExecutionStateConflict, RecordNotFoundError):
            pass


# ── service registry ────────────────────────────────────────────────────────

_SERVICES: dict[str, SourceVideoReaderService] = {}


def source_video_reader_service(services: Any) -> SourceVideoReaderService:
    key = str(services.root)
    instance = _SERVICES.get(key)
    if instance is None or instance.services is not services:
        instance = SourceVideoReaderService(services)
        _SERVICES[key] = instance
    return instance


def clear_source_video_reader_service_registry() -> None:
    _SERVICES.clear()


async def drain_source_video_reader_services() -> None:
    """Shutdown drain: terminalize every in-flight video read Task."""

    instances = list(_SERVICES.values())
    for instance in instances:
        await instance.drain()


def recover_interrupted_source_video_reads(services: Any) -> int:
    """Fail-close video read Tasks a dead process left QUEUED/RUNNING.

    Extraction state lives only in the dead process, so restart recovery
    terminalizes the Task with a retryable error instead of leaving
    waiters polling a RUNNING record no worker owns.
    """

    service = source_video_reader_service(services)
    recovered = 0
    for project_id in services.projects.discover_project_ids():
        for task in service.executions.list_tasks(project_id):
            if task.kind is not TaskKind.READ_SOURCE_VIDEO:
                continue
            if task.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                continue
            job = SourceVideoReadJob(
                project_id=project_id,
                task_id=task.task_id,
                logical_asset_id=str(
                    task.metadata.get("targetRef") or "",
                ).removeprefix("asset:"),
                version_id=str(task.metadata.get("assetVersionId") or ""),
                local_path=str(task.metadata.get("localPath") or ""),
                fps=float(task.metadata.get("fps") or 0),
                budget=str(task.metadata.get("budget") or "normal"),
                start_ms=task.metadata.get("startMs"),
                end_ms=task.metadata.get("endMs"),
                max_frames=int(
                    task.metadata.get("maxFrames") or DEFAULT_MAX_FRAMES,
                ),
            )
            service._fail_sync(  # pylint: disable=protected-access
                job,
                RuntimeError(
                    "video read was interrupted by a process restart; "
                    "retry the read",
                ),
            )
            recovered += 1
    return recovered
