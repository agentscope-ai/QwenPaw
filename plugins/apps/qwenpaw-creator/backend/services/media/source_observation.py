# -*- coding: utf-8 -*-
"""Time-window observation of original source footage (回原片核验).

Completes the video-memory two-step query paradigm: after
``query_source_memory`` locates candidate ``hitWindowsMs``, a specialist
calls ``observe_source_clip`` to cut that window from the original source
media, watch it through the configured VLM and confirm the finding before
using it as an editing decision. Runs as a ProjectExecutionStore task
(``TaskKind.OBSERVE_SOURCE_CLIP``) so the specialist tool can declare
``wait=TASK`` and the driver awaits the durable task record.

This module also owns the shared clip-encode helpers (budget derivation,
encode ladder, DashScope HQ path) that the source-memory build pipeline
imports — the dependency is one-way: ``source_memory`` imports from here.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess  # nosec B404 - fixed ffmpeg argv, no shell
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from domain.enums import TaskKind, TaskStatus
from domain.errors import ValidationError
from models import vlm_model
from models import config as model_config
from models.media_transport import DASHSCOPE_TEMP_UPLOAD_MAX_BYTES
from services.project_files.remote_cache import resolve_remote_cache
from services.runtime_files.errors import RecordNotFoundError
from services.runtime_files.execution_models import (
    TaskAttemptStatus,
    TaskRecord,
)
from services.runtime_files.execution_store import (
    ExecutionStateConflict,
    ProjectExecutionStore,
)
from services.runtime_files.runtime_dependencies import resolve_ffmpeg

logger = logging.getLogger("creator.source_observation")

# ── shared clip transport helpers (moved from source_memory) ────────────────
# Clip encoding for VLM observation. Non-DashScope OpenAI-compatible
# gateways receive the clip as an inline base64 data URL, so each clip
# must fit the configured inline transport limit after Base64 expansion
# (~4/3); encoding steps down this (max_dim, crf, fps) ladder until the
# segment fits.
CLIP_ENCODE_LADDER = (
    (720, 28, 8),
    (512, 30, 8),
    (384, 32, 6),
    (320, 35, 4),
    (256, 38, 3),
)
CLIP_SIZE_BUDGET_CAP_BYTES = 6 * 1024 * 1024
BASE64_EXPANSION = 4.0 / 3.0
CLIP_BUDGET_HEADROOM_BYTES = 64 * 1024
CLIP_MIN_WORKABLE_BUDGET_BYTES = 256 * 1024

# Clip transport for DashScope-bound VLMs: the clip travels through the
# model-bound temporary OSS upload (48h TTL, <=1GB) instead of an inline
# base64 body, so segments keep a high-quality encode mirroring the
# upstream OSS pipeline (max_dim 1024, crf 28, source frame rate).
HQ_CLIP_MAX_DIM = 1024
HQ_CLIP_CRF = 28
HQ_CLIP_MAX_BYTES = DASHSCOPE_TEMP_UPLOAD_MAX_BYTES


def require_ffmpeg() -> str:
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg is required for source clip encoding; set "
            "CREATOR_FFMPEG_PATH, install ffmpeg, or install imageio-ffmpeg",
        )
    return ffmpeg


def clip_size_budget_bytes() -> int:
    """Raw clip budget derived from the active transport limit.

    The inline pre-flight check in the VLM backend enforces
    ``get_vlm_max_inline_bytes`` on the raw file, while the gateway sees
    the Base64-expanded request body; budget against both, capped at a
    conservative default. Configurations too small for any workable
    segment clip are rejected up front instead of producing a budget
    that transport would later refuse.
    """
    inline_limit = model_config.get_vlm_max_inline_bytes()
    base64_safe = int(inline_limit / BASE64_EXPANSION)
    budget = (
        min(
            CLIP_SIZE_BUDGET_CAP_BYTES,
            inline_limit,
            base64_safe,
        )
        - CLIP_BUDGET_HEADROOM_BYTES
    )
    if budget < CLIP_MIN_WORKABLE_BUDGET_BYTES:
        raise ValidationError(
            "VLM max_inline_bytes is too small for source-memory clips: "
            f"derived budget {budget} bytes is below the workable minimum "
            f"{CLIP_MIN_WORKABLE_BUDGET_BYTES} bytes",
        )
    return budget


def clip_segment_sync(
    local_path: Path,
    out_path: Path,
    start_sec: float,
    end_sec: float,
    max_dim: int,
    crf: int,
    fps: int,
) -> Path:
    """Encode one source segment for VLM observation."""
    ffmpeg = require_ffmpeg()
    duration = max(0.5, end_sec - start_sec)
    scale = (
        f"scale='min({max_dim},iw)':'min({max_dim},ih)':"
        "force_original_aspect_ratio=decrease,"
        "pad=ceil(iw/2)*2:ceil(ih/2)*2"
    )
    command = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-ss",
        str(start_sec),
        "-t",
        str(duration),
        "-i",
        str(local_path),
        "-vf",
        scale,
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        str(crf),
        "-an",
        "-threads",
        "4",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(  # nosec B603
        command,
        capture_output=True,
        timeout=1800,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0 or not out_path.exists():
        raise RuntimeError(
            "ffmpeg segment clip failed: "
            f"{proc.stderr.decode('utf-8', 'replace')[-300:]}",
        )
    return out_path


def clip_segment_within_budget_sync(
    local_path: Path,
    out_path: Path,
    start_sec: float,
    end_sec: float,
) -> Path:
    """Encode a segment, stepping down the ladder until it fits the
    inline transport budget of OpenAI-compatible gateways."""
    budget = clip_size_budget_bytes()
    last_size = 0
    for max_dim, crf, fps in CLIP_ENCODE_LADDER:
        clip_segment_sync(
            local_path,
            out_path,
            start_sec,
            end_sec,
            max_dim,
            crf,
            fps,
        )
        last_size = out_path.stat().st_size
        if last_size <= budget:
            return out_path
        logger.info(
            "segment clip %s too large at %dpx (%d bytes > %d), "
            "stepping down",
            out_path.name,
            max_dim,
            last_size,
            budget,
        )
    raise RuntimeError(
        f"segment clip stays above transport budget: {last_size} bytes",
    )


def clip_segment_hq_sync(
    local_path: Path,
    out_path: Path,
    start_sec: float,
    end_sec: float,
) -> Path:
    """High-quality segment encode for the DashScope temporary-OSS path.

    Mirrors the upstream ``clip_and_upload_video`` settings (1024px,
    crf 28) and keeps the source frame rate; the temporary upload takes
    files up to 1GB so no inline base64 budget applies."""
    ffmpeg = require_ffmpeg()
    duration = max(0.5, end_sec - start_sec)
    scale = (
        f"scale='min({HQ_CLIP_MAX_DIM},iw)':'min({HQ_CLIP_MAX_DIM},ih)':"
        "force_original_aspect_ratio=decrease,"
        "pad=ceil(iw/2)*2:ceil(ih/2)*2"
    )
    command = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-ss",
        str(start_sec),
        "-t",
        str(duration),
        "-i",
        str(local_path),
        "-vf",
        scale,
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        str(HQ_CLIP_CRF),
        "-an",
        "-threads",
        "4",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    proc = subprocess.run(  # nosec B603
        command,
        capture_output=True,
        timeout=1800,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0 or not out_path.exists():
        raise RuntimeError(
            "ffmpeg hq segment clip failed: "
            f"{proc.stderr.decode('utf-8', 'replace')[-300:]}",
        )
    if out_path.stat().st_size > HQ_CLIP_MAX_BYTES:
        raise RuntimeError(
            "hq segment clip exceeds the temporary upload limit: "
            f"{out_path.stat().st_size} bytes",
        )
    return out_path


def clip_segment_for_transport_sync(
    local_path: Path,
    out_path: Path,
    start_sec: float,
    end_sec: float,
) -> Path:
    """Pick the encode matching the active VLM transport channel.

    DashScope providers upload through the model-bound temporary OSS and
    get the high-quality encode; any HQ failure (or a non-DashScope
    gateway) falls back to the inline base64 ladder."""
    if vlm_model.uses_dashscope_transport():
        try:
            return clip_segment_hq_sync(
                local_path,
                out_path,
                start_sec,
                end_sec,
            )
        except Exception as error:  # pylint: disable=broad-except
            logger.warning(
                "hq clip failed for %s (%s); falling back to the inline "
                "ladder",
                out_path.name,
                error,
            )
    return clip_segment_within_budget_sync(
        local_path,
        out_path,
        start_sec,
        end_sec,
    )


# ── observe_source_clip task ────────────────────────────────────────────────

# Window bounds keep single observations cheap and clip encodes within
# transport budgets; wider questions belong to query_source_memory or a
# read_source_video coarse scan.
OBSERVE_MAX_WINDOW_MS = 120_000
# DashScope rejects video inputs shorter than ~2s ("The video file is too
# short"); observations below that are frame questions, not clip questions.
OBSERVE_MIN_WINDOW_MS = 2_000
OBSERVATION_FPS = 2.0
OBSERVATION_MAX_TOKENS = 4096

OBSERVATION_PROMPT = """You are the Source Intelligence clip verifier for
QwenPaw Creator. You are watching ONE continuous clip cut from the original
source footage; the clip covers {start_label} to {end_label} of the source
timeline (all timestamps you report must be absolute source timestamps
inside this window, in mm:ss.mmm form).

Answer the question strictly from what is visible/audible in this clip.
Quote concrete visual evidence with timestamps for every claim. If the
question's premise does not match the clip, say so plainly — never invent
content. Answer in the question's language.

Question: {question}
"""


def _fmt_ms(value_ms: int) -> str:
    seconds = value_ms / 1000.0
    minutes = int(seconds // 60)
    return f"{minutes:02d}:{seconds - minutes * 60:06.3f}"


def _stable_id(prefix: str, project_id: str, key: str) -> str:
    return (
        f"{prefix}-"
        + uuid5(
            NAMESPACE_URL,
            f"qwenpaw-creator:source-observation:{prefix}:"
            f"{project_id}:{key}",
        ).hex
    )


@dataclass(frozen=True, slots=True)
class SourceObservationJob:
    project_id: str
    task_id: str
    logical_asset_id: str
    version_id: str
    local_path: str
    start_ms: int
    end_ms: int
    question: str


def resolve_local_source_media(
    services: Any,
    executions: ProjectExecutionStore,
    project_id: str,
    logical_asset_id: str,
) -> tuple[str, Path]:
    """Resolve a logical asset to its selected version's local file.

    Shared by the observe/read tools: panel uploads resolve through the
    Project asset store, remote sources through the ingest cache.
    """
    snapshot = services.projects.read(project_id)
    source = next(
        (
            item
            for item in snapshot.project.sources.sources.items.values()
            if item.logical_asset_id == logical_asset_id
        ),
        None,
    )
    if source is None:
        raise ValidationError(
            f"unknown source asset: {logical_asset_id}",
        )
    version_id = source.selected_asset_version_id
    version = snapshot.project.assets.source_versions_by_id.get(
        version_id,
    )
    if version is None:
        raise ValidationError(
            f"selected version {version_id} not found for "
            f"asset {logical_asset_id}",
        )
    project_root = services.projects.project_root(project_id)
    if version.file_id is not None:
        indexed = snapshot.project.assets.files_by_id.get(
            version.file_id,
        )
        if indexed is not None:
            candidate = Path(project_root, indexed.relative_uri)
            if candidate.is_file():
                return version_id, candidate
    cache = resolve_remote_cache(
        Path(project_root),
        version,
        executions.list_tasks(project_id),
    )
    if cache is not None and Path(cache.path).is_file():
        return version_id, Path(cache.path)
    raise ValidationError(
        f"素材 {logical_asset_id} 没有可用的本地媒体文件，" "无法抽取原片片段核验",
    )


class SourceObservationService:
    """Owns observe-clip task scheduling for one runtime root."""

    def __init__(self, services: Any) -> None:
        self.services = services
        self.executions = ProjectExecutionStore(services.root)
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._job_specs: dict[str, SourceObservationJob] = {}

    # -- resolution ----------------------------------------------------------

    def _resolve_local_media(
        self,
        project_id: str,
        logical_asset_id: str,
    ) -> tuple[str, Path]:
        return resolve_local_source_media(
            self.services,
            self.executions,
            project_id,
            logical_asset_id,
        )

    # -- scheduling ----------------------------------------------------------

    async def schedule_observe_clip(
        self,
        *,
        project_id: str,
        logical_asset_id: str,
        start_ms: int,
        end_ms: int,
        question: str,
        idempotency_key: str,
        caused_by_request_id: str | None = None,
    ) -> TaskRecord:
        if not question.strip():
            raise ValidationError("observe_source_clip 需要 question")
        window = end_ms - start_ms
        if start_ms < 0 or window < OBSERVE_MIN_WINDOW_MS:
            raise ValidationError(
                "observation window is too small: "
                f"[{start_ms}, {end_ms})ms is below the "
                f"{OBSERVE_MIN_WINDOW_MS}ms minimum",
            )
        if window > OBSERVE_MAX_WINDOW_MS:
            raise ValidationError(
                "observation window is too large: "
                f"{window}ms exceeds the {OBSERVE_MAX_WINDOW_MS}ms cap; "
                "narrow the window (query_source_memory hit windows can "
                "be observed one at a time)",
            )
        version_id, local_path = await asyncio.to_thread(
            self._resolve_local_media,
            project_id,
            logical_asset_id,
        )
        task = await asyncio.to_thread(
            self._admit_sync,
            project_id,
            logical_asset_id,
            version_id,
            local_path,
            start_ms,
            end_ms,
            question,
            idempotency_key,
            caused_by_request_id,
        )
        job = SourceObservationJob(
            project_id=project_id,
            task_id=task.task_id,
            logical_asset_id=logical_asset_id,
            version_id=version_id,
            local_path=str(local_path),
            start_ms=start_ms,
            end_ms=end_ms,
            question=question,
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
                    "observation worker was lost (process restarted); "
                    "retry the observation",
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

        An observation cannot survive the process (the VLM call and the
        temporary clip live in memory), so shutdown must terminalize the
        owning Task instead of leaving it RUNNING for waiters that poll it
        after restart.
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
                    "observation was interrupted by shutdown; "
                    "retry the observation",
                ),
            )

    def _admit_sync(  # pylint: disable=too-many-arguments
        self,
        project_id: str,
        logical_asset_id: str,
        version_id: str,
        local_path: Path,
        start_ms: int,
        end_ms: int,
        question: str,
        idempotency_key: str,
        caused_by_request_id: str | None,
    ) -> TaskRecord:
        task_id = _stable_id("observe", project_id, idempotency_key)
        try:
            existing = self.executions.get_task(project_id, task_id)
        except RecordNotFoundError:
            existing = None
        if existing is not None:
            # Converge on the durable record: the driver awaits its
            # terminal state, so replays never re-bill the VLM call.
            return existing
        target_ref = f"asset:{logical_asset_id}"
        candidate = TaskRecord(
            task_id=task_id,
            project_id=project_id,
            kind=TaskKind.OBSERVE_SOURCE_CLIP,
            request_fingerprint=uuid5(
                NAMESPACE_URL,
                "observe-clip:" f"{version_id}:{start_ms}:{end_ms}:{question}",
            ).hex,
            idempotency_key=task_id,
            input_refs=[target_ref],
            caused_by_request_id=caused_by_request_id,
            metadata={
                "targetRef": target_ref,
                "assetVersionId": version_id,
                "startMs": start_ms,
                "endMs": end_ms,
                "question": question,
                "localPath": str(local_path),
            },
        )
        return self.executions.create_task(candidate)

    def _spawn(self, job: SourceObservationJob) -> None:
        current = self._jobs.get(job.task_id)
        if current is not None and not current.done():
            return
        worker = asyncio.create_task(
            self._drive(job),
            name=f"observe-clip:{job.task_id}",
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

    async def _drive(self, job: SourceObservationJob) -> None:
        try:
            await self._execute(job)
        except asyncio.CancelledError:  # pylint: disable=try-except-raise
            raise
        except Exception as error:  # pylint: disable=broad-except
            logger.exception(
                "observe clip failed: project=%s task=%s",
                job.project_id,
                job.task_id,
            )
            await asyncio.to_thread(self._fail_sync, job, error)

    async def _execute(self, job: SourceObservationJob) -> None:
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
                "startMs": job.start_ms,
                "endMs": job.end_ms,
            },
        )
        local_path = Path(job.local_path)
        if not local_path.is_file():
            raise RuntimeError(
                f"source media is no longer available: {local_path}",
            )
        answer = await self._observe(job, local_path)
        await asyncio.to_thread(
            self.executions.append_attempt,
            job.project_id,
            job.task_id,
            event_id=f"{attempt_id}-succeeded",
            attempt_id=attempt_id,
            status=TaskAttemptStatus.SUCCEEDED,
            output={
                "answer": answer,
                "windowMs": [job.start_ms, job.end_ms],
                "clipDurationMs": job.end_ms - job.start_ms,
                "assetId": job.logical_asset_id,
                "versionId": job.version_id,
            },
        )

    async def _observe(
        self,
        job: SourceObservationJob,
        local_path: Path,
    ) -> str:
        prompt = OBSERVATION_PROMPT.format(
            start_label=_fmt_ms(job.start_ms),
            end_label=_fmt_ms(job.end_ms),
            question=job.question.strip(),
        )
        with tempfile.TemporaryDirectory(prefix="observe-clip-") as tmp:
            clip_path = Path(tmp) / f"{job.task_id}.mp4"
            await asyncio.to_thread(
                clip_segment_for_transport_sync,
                local_path,
                clip_path,
                job.start_ms / 1000.0,
                job.end_ms / 1000.0,
            )
            content = [
                vlm_model.multimodal_media_part(
                    clip_path.as_uri(),
                    "video",
                    fps=OBSERVATION_FPS,
                ),
                {"type": "text", "text": prompt},
            ]
            response = await vlm_model.chat_completion(
                content,
                temperature=0.3,
                max_tokens=OBSERVATION_MAX_TOKENS,
            )
        answer = str(response or "").strip()
        if not answer:
            raise RuntimeError("VLM returned an empty observation")
        return answer

    def _fail_sync(
        self,
        job: SourceObservationJob,
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
                        "code": "OBSERVE_CLIP_FAILED",
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
                            "code": "OBSERVE_CLIP_FAILED",
                            "message": str(error)[:2000],
                        },
                    },
                )
        except (ExecutionStateConflict, RecordNotFoundError):
            pass


# ── service registry ────────────────────────────────────────────────────────

_SERVICES: dict[str, SourceObservationService] = {}


def source_observation_service(services: Any) -> SourceObservationService:
    key = str(services.root)
    instance = _SERVICES.get(key)
    if instance is None or instance.services is not services:
        instance = SourceObservationService(services)
        _SERVICES[key] = instance
    return instance


def clear_source_observation_service_registry() -> None:
    _SERVICES.clear()


async def drain_source_observation_services() -> None:
    """Shutdown drain: terminalize every in-flight observation Task."""

    instances = list(_SERVICES.values())
    for instance in instances:
        await instance.drain()


def recover_interrupted_source_observations(services: Any) -> int:
    """Fail-close observation Tasks a dead process left QUEUED/RUNNING.

    The VLM call behind an observation is billed per invocation and has no
    durable provider id to resume, so restart recovery terminalizes the
    Task with a retryable error instead of leaving waiters polling a
    RUNNING record no worker owns.
    """

    service = source_observation_service(services)
    recovered = 0
    for project_id in services.projects.discover_project_ids():
        for task in service.executions.list_tasks(project_id):
            if task.kind is not TaskKind.OBSERVE_SOURCE_CLIP:
                continue
            if task.status not in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                continue
            job = SourceObservationJob(
                project_id=project_id,
                task_id=task.task_id,
                logical_asset_id=str(
                    task.metadata.get("targetRef") or "",
                ).removeprefix("asset:"),
                version_id=str(task.metadata.get("assetVersionId") or ""),
                local_path=str(task.metadata.get("localPath") or ""),
                start_ms=int(task.metadata.get("startMs") or 0),
                end_ms=int(task.metadata.get("endMs") or 0),
                question=str(task.metadata.get("question") or ""),
            )
            service._fail_sync(  # pylint: disable=protected-access
                job,
                RuntimeError(
                    "observation was interrupted by a process restart; "
                    "retry the observation",
                ),
            )
            recovered += 1
    return recovered
