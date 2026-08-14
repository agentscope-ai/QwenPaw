# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-lines
"""Long-source hierarchical graph memory inside Source Intelligence.

Write path: after ``commit_source_intelligence`` publishes a regular index,
sources longer than the threshold get a background Task (ungated: no
execution authorization) that builds the vendored video-memory
hierarchical graph:
P1 ffmpeg frame-diff scene segmentation → P2 one VLM subgraph extraction
per macro (bounded concurrency) in parallel with ASR transcription →
P3 text-only aggregation plus full-node embedding (BM25-only text index
when no embedding backend is configured). Artifacts live in
``runtime/source-intelligence/<index-id>/memory/`` and are invalidated by
``sourceChecksum``.

Read path: ``query_source_memory`` dispatches nine query types over the
vendored :class:`MemoryToolkit` with an in-process graph cache; semantic
lookups embed the query on the fly through the Creator embedding client
and degrade to BM25 text search whenever embeddings are unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess  # nosec B404 - fixed ffmpeg argv, no shell
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Mapping
from uuid import NAMESPACE_URL, uuid5

import numpy as np
from pydantic import Field

from domain.enums import TaskKind, TaskStatus
from domain.errors import ValidationError
from models import asr_model, embedding_model, vlm_model
from models import config as model_config
from schemas.assets import (
    SemanticIndexEntry,
    SourceIntelligenceIndex,
    SourceMemoryRef,
    SourceModelRunRef,
)
from schemas.common import StrictModel
from services.media.source_observation import (
    clip_segment_for_transport_sync,
    clip_segment_hq_sync,
    clip_segment_sync,
    clip_segment_within_budget_sync,
    clip_size_budget_bytes,
)
from services.runtime_files.errors import RecordNotFoundError
from services.runtime_files.execution_models import (
    ExecutionAuthorizationStatus,
    TaskAttemptStatus,
    TaskRecord,
)
from services.runtime_files.execution_store import (
    ExecutionStateConflict,
    ProjectExecutionStore,
)
from services.runtime_files.runtime_dependencies import resolve_ffmpeg
from vendor.media_toolkit.video_memory.aggregation import aggregate_hierarchy
from vendor.media_toolkit.video_memory.embeddings import EmbeddingIndex
from vendor.media_toolkit.video_memory.json_utils import extract_json
from vendor.media_toolkit.video_memory.merge import (
    merged_graph_payload,
    prefix_graph_payload,
    prefix_index_nodes,
)
from vendor.media_toolkit.video_memory.prompts import (
    SUBGRAPH_CONSTRUCTION_PROMPT,
)
from vendor.media_toolkit.video_memory.schema import (
    HierarchicalGraphMemory,
    MacroEvent,
    Subgraph,
)
from vendor.media_toolkit.video_memory.segmentation import (
    compute_cut_scores,
    decode_jpeg_to_hls,
    plan_segments,
)
from vendor.media_toolkit.video_memory.subgraph import (
    apply_subgraph_payload,
    build_segment_context,
)
from vendor.media_toolkit.video_memory.toolkit import MemoryToolkit

logger = logging.getLogger("creator.source_memory")

# Sources longer than this get a memory build (plan: 20 minutes).
MEMORY_BUILD_THRESHOLD_MS = 20 * 60 * 1000
# P2 subgraph extraction concurrency (plan window: 4-8).
SUBGRAPH_CONCURRENCY = 6
# P1 detection sampling (matches the upstream pipeline defaults).
DETECT_FPS = 0.25
FRAME_WORKERS = 10
MIN_SCENE_SEC = 30.0
MAX_SCENE_SEC = 300.0

# Chunked P1→P2 pipeline (upstream ``build_memory.sh --chunk-sec``):
# multi-hour sources are detected hour by hour and each chunk's subgraph
# extraction starts while the next chunk is still being detected.
CHUNK_SEC = 3600.0

SUBGRAPH_MAX_TOKENS = 16384
AGGREGATION_MAX_TOKENS = 8192
SUBGRAPH_RETRIES = 2
PROJECTION_REVIEW_MAX_TOKENS = 4096

# Outer-VLM review of the P3 projection drafts. Not an agent prompt
# (no placeholder whitelist involvement) — a Creator-side constant like
# the vendored pipeline prompts.
PROJECTION_REVIEW_PROMPT = """You are the Source Intelligence reviewer.
Below are draft catalog entries projected from a hierarchical memory of
a long video: one overall summary plus per-super-event semantic entries
with millisecond time windows. Each entry carries an immutable
"entryId".

Review the drafts: fix wording, drop entries that are vague, redundant
or internally inconsistent. You may only edit text, tags and
confidence; keep each kept entry's entryId exactly as given, never
invent new entries and never change startMs/endMs. Do not invent new
facts. Return ONLY a JSON object:
{"summary": str, "semanticEntries": [{"entryId": str, "text": str,
"tags": [str], "startMs": int, "endMs": int, "confidence": float}]}

Drafts:
"""

MEMORY_DIR_NAME = "memory"
GRAPH_FILENAME = "graph_memory.json"
EMBEDDINGS_FILENAME = "embeddings.npz"
META_FILENAME = "memory_meta.json"
PROJECTION_FILENAME = "projection.json"
# Durable stage-level checkpoints (upstream keeps 01_macros.json /
# asr_transcript.json / subgraphs/*.json): an interrupted build resumes
# from persisted P1 segments, the billed ASR transcript and per-macro
# subgraph payloads instead of replaying paid model calls.
BUILD_DIR_NAME = "build"
SEGMENTS_CHECKPOINT_FILENAME = "segments.json"
TRANSCRIPT_CHECKPOINT_FILENAME = "transcript.json"
SUBGRAPH_CHECKPOINT_DIRNAME = "subgraphs"

SOURCE_MEMORY_OPERATION = "build_source_memory"

QUERY_TYPES = (
    "summary",
    "super_events",
    "macro_events",
    "subgraph",
    "search_nodes",
    "search_ocr",
    "search_asr",
    "by_time",
    "enumerate",
)


def memory_build_threshold_ms() -> int:
    """Threshold in ms; env override supports isolated-stack testing."""
    raw = os.environ.get("CREATOR_MEMORY_BUILD_THRESHOLD_MS", "")
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return MEMORY_BUILD_THRESHOLD_MS
    return parsed if parsed > 0 else MEMORY_BUILD_THRESHOLD_MS


class SourceMemorySemanticDraft(StrictModel):
    """One projected semantic entry draft (producer: source_memory)."""

    text: str = Field(min_length=1)
    tags: list[str]
    start_ms: int = Field(alias="startMs", ge=0)
    end_ms: int = Field(alias="endMs", gt=0)
    confidence: float = Field(ge=0.0, le=1.0)


class ProjectionReview(StrictModel):
    """Outer-VLM review verdict attached to a projection."""

    status: Literal["approved"] = "approved"
    model: str = Field(min_length=1)
    reviewed_at: str = Field(alias="reviewedAt", min_length=1)


class SourceMemoryProjection(StrictModel):
    """Summary/semantics projected from the P3 hierarchy.

    Drafts are reviewed by the outer Source Intelligence VLM during the
    build; only reviewed projections are folded into the standard index
    surfaces. The immutable index file is never rewritten.
    """

    producer: Literal["source_memory"] = "source_memory"
    index_id: str = Field(alias="indexId", min_length=1)
    summary: str = Field(min_length=1)
    semantic_entries: list[SourceMemorySemanticDraft] = Field(
        alias="semanticEntries",
    )
    review: ProjectionReview | None = None


# ── Artifact locations & hydration ──────────────────────────────────────────


def memory_dir(project_root: Path, index_id: str) -> Path:
    return (
        project_root
        / "runtime"
        / "source-intelligence"
        / index_id
        / MEMORY_DIR_NAME
    )


def build_dir(project_root: Path, index_id: str) -> Path:
    """Durable stage-checkpoint directory for one memory build."""
    return memory_dir(project_root, index_id) / BUILD_DIR_NAME


def _load_checkpoint(path: Path, source_checksum: str) -> Any:
    """Return the checkpointed payload, or None when absent/stale."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, Mapping):
        return None
    if raw.get("sourceChecksum") != source_checksum:
        return None
    return raw.get("data")


def _write_checkpoint(path: Path, source_checksum: str, data: Any) -> None:
    """Atomically persist one stage checkpoint keyed by source checksum."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(
            {"sourceChecksum": source_checksum, "data": data},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def has_build_checkpoint(
    project_root: Path,
    index_id: str,
    source_checksum: str,
) -> bool:
    """True when any durable stage checkpoint matches this source."""
    directory = build_dir(project_root, index_id)
    if (
        _load_checkpoint(
            directory / SEGMENTS_CHECKPOINT_FILENAME,
            source_checksum,
        )
        is not None
    ):
        return True
    subgraph_root = directory / SUBGRAPH_CHECKPOINT_DIRNAME
    try:
        candidates = sorted(subgraph_root.glob("macro_*.json"))
    except OSError:
        return False
    return any(
        _load_checkpoint(candidate, source_checksum) is not None
        for candidate in candidates
    )


def load_memory_ref(
    project_root: Path,
    index_id: str,
    source_checksum: str,
) -> SourceMemoryRef | None:
    """Load the built-memory pointer; stale checksums invalidate it."""
    directory = memory_dir(project_root, index_id)
    meta_path = directory / META_FILENAME
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, Mapping):
        return None
    if meta.get("sourceChecksum") != source_checksum:
        return None
    # graph_memory.json is the source of truth; a missing embeddings.npz
    # only degrades retrieval to BM25 text search (_load_toolkit_sync
    # rebuilds the sparse index from graph nodes), it must not invalidate
    # the whole memory.
    if not (directory / GRAPH_FILENAME).is_file():
        return None
    built_at = str(meta.get("builtAt") or "")
    macro_count = meta.get("macroCount")
    if not built_at or not isinstance(macro_count, int):
        return None
    relative = directory.relative_to(project_root).as_posix()
    return SourceMemoryRef(
        graphPath=f"{relative}/{GRAPH_FILENAME}",
        embeddingsPath=f"{relative}/{EMBEDDINGS_FILENAME}",
        builtAt=built_at,
        macroCount=macro_count,
    )


SOURCE_MEMORY_RUN_ID = "source_memory"


def merge_projection_semantics(project_root: Path, index: Any) -> None:
    """Fold the reviewed P3 projection into a loaded index, in memory.

    Only projections carrying an approved outer-VLM review are merged
    (fail-close for unreviewed drafts). The Root digest is appended to
    ``index.summary`` and the SuperEvent entries join ``semanticEntries``
    with ``modelRunId=source_memory``; the immutable index file on disk
    stays untouched (same hydrated-only contract as ``memoryRef``).
    """
    if index.memory_ref is None:
        return
    directory = memory_dir(project_root, index.id)
    try:
        meta = json.loads(
            (directory / META_FILENAME).read_text(encoding="utf-8"),
        )
        raw = json.loads(
            (directory / PROJECTION_FILENAME).read_text(encoding="utf-8"),
        )
        projection = SourceMemoryProjection.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValueError):
        return
    if projection.review is None or projection.review.status != "approved":
        return
    if not isinstance(meta, Mapping):
        return
    if meta.get("sourceChecksum") != index.source_checksum:
        return
    built_at = str(meta.get("builtAt") or "")
    if not built_at:
        return
    evidence = [f"memory://{index.id}/{GRAPH_FILENAME}"]
    common: dict[str, Any] = {
        "assetVersionId": index.asset_version_id,
        "sourceChecksum": index.source_checksum,
        "modelRunId": SOURCE_MEMORY_RUN_ID,
        "evidenceFrameRefs": evidence,
        "createdAt": built_at,
    }
    duration_ms = index.media.duration_ms
    # Reviewed Root digest enters the standard summary surface with a
    # clear origin marker (and also as an anchor semantic entry).
    marker = "[长素材记忆摘要 · 已审校]"
    if marker not in index.summary:
        index.summary = f"{index.summary}\n\n{marker} {projection.summary}"
    drafts: list[SemanticIndexEntry] = [
        SemanticIndexEntry(
            id="sem-mem-summary",
            text=projection.summary,
            tags=["memory", "summary"],
            confidence=0.6,
            **common,
        ),
    ]
    for n, draft in enumerate(projection.semantic_entries):
        end_ms = draft.end_ms
        if duration_ms is not None:
            end_ms = min(end_ms, duration_ms)
        if end_ms <= draft.start_ms:
            continue
        drafts.append(
            SemanticIndexEntry(
                id=f"sem-mem-{n:03d}",
                text=draft.text,
                tags=draft.tags,
                startMs=draft.start_ms,
                endMs=end_ms,
                confidence=draft.confidence,
                **common,
            ),
        )
    existing_ids = {entry.id for entry in index.semantic_entries}
    index.semantic_entries.extend(
        entry for entry in drafts if entry.id not in existing_ids
    )
    if SOURCE_MEMORY_RUN_ID not in {run.id for run in index.model_runs}:
        index.model_runs.append(
            SourceModelRunRef(
                id=SOURCE_MEMORY_RUN_ID,
                provider="creator",
                model="source-memory-p3",
            ),
        )


def has_built_memory(
    project_root: Path,
    project: Any,
    logical_asset_id: str,
) -> bool:
    """True when the asset's current intelligence has a valid memory."""
    for source in project.sources.sources.items.values():
        if source.logical_asset_id != logical_asset_id:
            continue
        selected = source.current_intelligence_version_id
        if not selected:
            return False
        record = project.assets.intelligence_versions_by_id.get(selected)
        if record is None:
            return False
        return (
            load_memory_ref(
                project_root,
                record.intelligence_version_id,
                record.source_checksum,
            )
            is not None
        )
    return False


def list_built_memories(
    project_root: Path,
    project: Any,
) -> list[tuple[str, str, str]]:
    """Every source whose current intelligence has a valid built memory.

    Returns sorted ``(logical_asset_id, index_id, source_checksum)``
    tuples — the enumeration surface for the project-scope merged
    memory (upstream ``merge_memories`` directory scan equivalent).
    """
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for source in project.sources.sources.items.values():
        logical_asset_id = source.logical_asset_id
        if not logical_asset_id or logical_asset_id in seen:
            continue
        seen.add(logical_asset_id)
        selected = source.current_intelligence_version_id
        if not selected:
            continue
        record = project.assets.intelligence_versions_by_id.get(selected)
        if record is None:
            continue
        ref = load_memory_ref(
            project_root,
            record.intelligence_version_id,
            record.source_checksum,
        )
        if ref is not None:
            out.append(
                (
                    logical_asset_id,
                    record.intelligence_version_id,
                    record.source_checksum,
                ),
            )
    return sorted(out)


# ── ffmpeg helpers (Creator-owned IO around the vendored planning) ─────────


def _require_ffmpeg() -> str:
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg is required for source memory builds; set "
            "CREATOR_FFMPEG_PATH, install ffmpeg, or install imageio-ffmpeg",
        )
    return ffmpeg


def _seek_jpeg(
    ffmpeg: str,
    video_path: str,
    ts: float,
    scale: str,
    quality: int,
    timeout: int,
) -> bytes | None:
    command = [
        ffmpeg,
        "-nostdin",
        "-v",
        "error",
        "-ss",
        str(ts),
        "-i",
        video_path,
        "-an",
        "-frames:v",
        "1",
        "-vf",
        f"scale={scale}",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "-q:v",
        str(quality),
        "pipe:1",
    ]
    try:
        proc = subprocess.run(  # nosec B603
            command,
            capture_output=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return None
    return proc.stdout if proc.returncode == 0 and proc.stdout else None


def _detect_segments_sync(
    local_path: Path,
    start_sec: float,
    end_sec: float,
) -> list[tuple[float, float]]:
    """Phase 1: parallel frame-diff scene detection for one time range
    (no API calls). Chunked builds call this per chunk; chunk edges are
    forced segment boundaries exactly like the upstream chunk pipeline."""
    ffmpeg = _require_ffmpeg()
    span = max(0.0, end_sec - start_sec)
    n_frames = max(4, int(span * DETECT_FPS))
    timestamps = [
        start_sec + i / DETECT_FPS
        for i in range(n_frames)
        if start_sec + i / DETECT_FPS < end_sec
    ] or [start_sec]

    def _extract(ts: float) -> tuple[float, bytes | None]:
        return ts, _seek_jpeg(
            ffmpeg,
            str(local_path),
            ts,
            "360:-2",
            quality=10,
            timeout=30,
        )

    with ThreadPoolExecutor(max_workers=FRAME_WORKERS) as pool:
        results = list(pool.map(_extract, timestamps))

    hls_frames = []
    for ts, data in results:
        if data is None:
            continue
        hls = decode_jpeg_to_hls(data)
        if hls is not None:
            hls_frames.append((ts, hls))
    logger.info(
        "source memory P1: %d/%d detection frames decoded "
        "(range %.0f-%.0fs)",
        len(hls_frames),
        n_frames,
        start_sec,
        end_sec,
    )
    cut_times, cut_scores = compute_cut_scores(hls_frames)
    return plan_segments(
        cut_times,
        cut_scores,
        start_sec=start_sec,
        end_sec=end_sec,
        min_scene_sec=MIN_SCENE_SEC,
        max_scene_sec=MAX_SCENE_SEC,
    )


def _chunk_plan(duration_sec: float) -> list[tuple[float, float]]:
    """Split the source into detection chunks of at most CHUNK_SEC.

    A trailing remainder shorter than MIN_SCENE_SEC folds into the
    previous chunk so no chunk yields degenerate segments."""
    if duration_sec <= CHUNK_SEC:
        return [(0.0, duration_sec)]
    chunks: list[tuple[float, float]] = []
    start = 0.0
    while start < duration_sec:
        end = min(start + CHUNK_SEC, duration_sec)
        chunks.append((start, end))
        start = end
    if len(chunks) >= 2 and (chunks[-1][1] - chunks[-1][0]) < MIN_SCENE_SEC:
        last = chunks.pop()
        prev = chunks.pop()
        chunks.append((prev[0], last[1]))
    return chunks


# Clip encoding lives in services.media.source_observation (shared with
# the observe_source_clip verification tool; the dependency is one-way:
# this module imports from it). Private aliases keep the existing build
# call sites and test patch points on this module working.
_clip_size_budget_bytes = clip_size_budget_bytes
_clip_segment_sync = clip_segment_sync
_clip_segment_within_budget_sync = clip_segment_within_budget_sync
_clip_segment_hq_sync = clip_segment_hq_sync
_clip_segment_for_transport_sync = clip_segment_for_transport_sync


def _segment_fps(duration_sec: float) -> float:
    """Match the Source Intelligence native sampling tiers."""
    if duration_sec <= 120:
        return 2.0
    if duration_sec <= 600:
        return 1.0
    return 0.5


def _merge_asr_into_macros(
    macros: list[MacroEvent],
    transcript: list[dict[str, float | str]],
) -> None:
    """Merge ASR transcript into macro events by time-range overlap."""
    if not transcript:
        return
    for macro in macros:
        ms, me = macro.time_range
        texts = [
            str(segment["text"])
            for segment in transcript
            if float(segment["start_sec"]) < me
            and float(segment["end_sec"]) > ms
        ]
        if texts:
            macro.asr_text = " ".join(texts)


# ── Build job ───────────────────────────────────────────────────────────────


def _stable_id(prefix: str, project_id: str, key: str) -> str:
    return (
        f"{prefix}-"
        + uuid5(
            NAMESPACE_URL,
            f"qwenpaw-creator:source-memory:{prefix}:{project_id}:{key}",
        ).hex
    )


class SourceMemoryBuildJob(StrictModel):
    project_id: str
    task_id: str
    authorization_id: str | None
    index_id: str
    asset_id: str
    asset_version_id: str
    source_checksum: str
    duration_ms: int
    local_path: str


class SourceMemoryService:
    """Owns memory build scheduling and memory queries for one root."""

    def __init__(self, services: Any) -> None:
        self.services = services
        self.executions = ProjectExecutionStore(services.root)
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._toolkits: dict[str, tuple[float, MemoryToolkit]] = {}
        self._merged_toolkits: dict[
            str,
            tuple[tuple, MemoryToolkit, dict[str, str]],
        ] = {}
        self._toolkits_lock = asyncio.Lock()

    # -- trigger -----------------------------------------------------------

    def should_build(
        self,
        index: SourceIntelligenceIndex,
        project_root: Path,
    ) -> bool:
        if index.media.media_kind != "video":
            return False
        duration_ms = index.media.duration_ms or 0
        if duration_ms <= memory_build_threshold_ms():
            return False
        # No embedding gate: without a configured embedding backend the
        # build still runs and persists a BM25-only text index.
        return (
            load_memory_ref(
                project_root,
                index.id,
                index.source_checksum,
            )
            is None
        )

    async def maybe_schedule_build(
        self,
        *,
        project_id: str,
        index: SourceIntelligenceIndex,
        local_path: Path | None,
        caused_by_request_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Schedule the background build after an index publication.

        Builds are ungated: no execution authorization is created and
        the task starts immediately.
        """
        project_root = self.services.projects.project_root(project_id)
        if not self.should_build(index, project_root):
            return None
        if local_path is None or not local_path.is_file():
            logger.info(
                "source memory build skipped: no local media for %s",
                index.id,
            )
            return None
        duration_ms = int(index.media.duration_ms or 0)
        task = await asyncio.to_thread(
            self._admit_sync,
            project_id,
            index,
            local_path,
            duration_ms,
            caused_by_request_id,
        )
        if task is None:
            return None
        job = SourceMemoryBuildJob(
            project_id=project_id,
            task_id=task.task_id,
            authorization_id=task.metadata.get("authorizationId"),
            index_id=index.id,
            asset_id=index.asset_id,
            asset_version_id=index.asset_version_id,
            source_checksum=index.source_checksum,
            duration_ms=duration_ms,
            local_path=str(local_path),
        )
        self._spawn(job)
        return {"taskId": task.task_id}

    def _admit_sync(
        self,
        project_id: str,
        index: SourceIntelligenceIndex,
        local_path: Path,
        duration_ms: int,
        caused_by_request_id: str | None,
    ) -> TaskRecord | None:
        task_id = _stable_id("memtask", project_id, index.id)
        try:
            existing = self.executions.get_task(project_id, task_id)
        except RecordNotFoundError:
            existing = None
        if existing is not None:
            if existing.status in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                return None
            if existing.status is TaskStatus.SUCCEEDED:
                return None
            # FAILED/CANCELLED builds are not auto-retried; a fresh index
            # version (new task id) restarts the flow.
            return None
        # Memory builds run without an execution-authorization gate: the
        # build starts as soon as the intelligence is published.
        target_ref = f"asset:{index.asset_id}"
        candidate = TaskRecord(
            task_id=task_id,
            project_id=project_id,
            kind=TaskKind.SOURCE_MEMORY_BUILD,
            request_fingerprint=uuid5(
                NAMESPACE_URL,
                f"source-memory:{index.id}:{index.source_checksum}",
            ).hex,
            idempotency_key=task_id,
            input_refs=[target_ref],
            caused_by_request_id=caused_by_request_id,
            metadata={
                "targetRef": target_ref,
                "analysisVersionId": index.id,
                "assetVersionId": index.asset_version_id,
                "sourceChecksum": index.source_checksum,
                "durationMs": duration_ms,
                "localPath": str(local_path),
            },
        )
        task = self.executions.create_task(candidate)
        logger.info(
            "source memory build admitted: project=%s task=%s index=%s "
            "duration=%dms",
            project_id,
            task_id,
            index.id,
            duration_ms,
        )
        return task

    def _spawn(self, job: SourceMemoryBuildJob) -> asyncio.Task[None] | None:
        current = self._jobs.get(job.task_id)
        if current is not None and not current.done():
            return current
        worker = asyncio.create_task(
            self._drive(job),
            name=f"source-memory:{job.task_id}",
        )
        self._jobs[job.task_id] = worker

        def discard(done: asyncio.Task[None]) -> None:
            if self._jobs.get(job.task_id) is done:
                self._jobs.pop(job.task_id, None)
            if not done.cancelled():
                try:
                    done.exception()
                except BaseException:  # pylint: disable=broad-except
                    pass

        worker.add_done_callback(discard)
        return worker

    async def _drive(self, job: SourceMemoryBuildJob) -> None:
        try:
            approved = await self._await_authorization(job)
            if not approved:
                return
            await self._execute(job)
        except asyncio.CancelledError:  # pylint: disable=try-except-raise
            raise
        except Exception as error:  # pylint: disable=broad-except
            logger.exception(
                "source memory build failed: project=%s task=%s",
                job.project_id,
                job.task_id,
            )
            await asyncio.to_thread(self._fail_sync, job, error)

    async def _await_authorization(self, job: SourceMemoryBuildJob) -> bool:
        if not job.authorization_id:
            return True
        while True:
            record = await asyncio.to_thread(
                self.executions.get_execution_authorization,
                job.project_id,
                job.authorization_id,
            )
            if record.status is ExecutionAuthorizationStatus.APPROVED:
                return True
            if record.status in {
                ExecutionAuthorizationStatus.REJECTED,
                ExecutionAuthorizationStatus.EXPIRED,
            }:
                await asyncio.to_thread(
                    self._cancel_sync,
                    job,
                    f"execution authorization {record.status.value.lower()}",
                )
                return False
            task = await asyncio.to_thread(
                self.executions.get_task,
                job.project_id,
                job.task_id,
            )
            if task.status is not TaskStatus.QUEUED:
                return False
            await asyncio.sleep(2.0)

    def _cancel_sync(self, job: SourceMemoryBuildJob, reason: str) -> None:
        try:
            self.executions.transition_task(
                job.project_id,
                job.task_id,
                expected_status=TaskStatus.QUEUED,
                status=TaskStatus.CANCELLED,
                updates={
                    "error": {
                        "code": "MEMORY_BUILD_DECLINED",
                        "message": reason,
                    },
                },
            )
        except ExecutionStateConflict:
            pass

    def _fail_sync(self, job: SourceMemoryBuildJob, error: Exception) -> None:
        try:
            task = self.executions.get_task(job.project_id, job.task_id)
            if task.status is TaskStatus.RUNNING:
                attempt_id = self._attempt_id(job, task.last_attempt_seq)
                self.executions.append_attempt(
                    job.project_id,
                    job.task_id,
                    event_id=f"{attempt_id}-failed",
                    attempt_id=attempt_id,
                    status=TaskAttemptStatus.FAILED,
                    error={
                        "code": "MEMORY_BUILD_FAILED",
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
                            "code": "MEMORY_BUILD_FAILED",
                            "message": str(error)[:2000],
                        },
                    },
                )
        except (ExecutionStateConflict, RecordNotFoundError):
            pass

    @staticmethod
    def _attempt_id(job: SourceMemoryBuildJob, attempt_seq: int) -> str:
        """Attempt ids must be fresh per retry round; the open RUNNING
        attempt keeps the id derived from the seq it was admitted at."""
        base = _stable_id("memattempt", job.project_id, job.index_id)
        return f"{base}-r{attempt_seq}"

    # -- build pipeline ------------------------------------------------------

    async def _execute(  # pylint: disable=too-many-statements,too-many-branches,too-many-locals
        self,
        job: SourceMemoryBuildJob,
    ) -> None:
        task = await asyncio.to_thread(
            self.executions.get_task,
            job.project_id,
            job.task_id,
        )
        if task.status is not TaskStatus.QUEUED:
            return
        attempt_id = self._attempt_id(job, task.last_attempt_seq + 1)
        # Converge on durable artifacts before spending anything: a
        # restart between persistence and the SUCCEEDED event must not
        # replay billed model calls under the same authorization.
        existing = await asyncio.to_thread(self._existing_ref, job)
        if existing is not None:
            await asyncio.to_thread(
                self.executions.append_attempt,
                job.project_id,
                job.task_id,
                event_id=f"{attempt_id}-running",
                attempt_id=attempt_id,
                status=TaskAttemptStatus.RUNNING,
                input={
                    "analysisVersionId": job.index_id,
                    "converged": True,
                },
            )
            await asyncio.to_thread(
                self.executions.append_attempt,
                job.project_id,
                job.task_id,
                event_id=f"{attempt_id}-succeeded",
                attempt_id=attempt_id,
                status=TaskAttemptStatus.SUCCEEDED,
                output={
                    "converged": True,
                    "graphPath": existing.graph_path,
                    "embeddingsPath": existing.embeddings_path,
                    "macroCount": existing.macro_count,
                },
                output_refs=[existing.graph_path],
            )
            logger.info(
                "source memory build converged on existing artifacts: "
                "task=%s",
                job.task_id,
            )
            return
        await asyncio.to_thread(
            self.executions.append_attempt,
            job.project_id,
            job.task_id,
            event_id=f"{attempt_id}-running",
            attempt_id=attempt_id,
            status=TaskAttemptStatus.RUNNING,
            input={
                "analysisVersionId": job.index_id,
                "durationMs": job.duration_ms,
            },
        )
        local_path = Path(job.local_path)
        if not local_path.is_file():
            raise RuntimeError(
                f"source media is no longer available: {local_path}",
            )
        duration_sec = job.duration_ms / 1000.0
        project_root = self.services.projects.project_root(job.project_id)
        checkpoints = build_dir(project_root, job.index_id)
        subgraph_ckpt_dir = checkpoints / SUBGRAPH_CHECKPOINT_DIRNAME

        # ASR first: every chunk's macros merge the transcript before
        # their subgraph prompts are built. Standalone (billed)
        # transcriptions are checkpointed and never replayed on resume.
        transcript = await self._resolve_transcript(
            job,
            local_path,
            checkpoints,
        )

        # Chunked P1→P2 pipeline with durable stage checkpoints: each
        # chunk is detected (or reloaded from its checkpoint) and its
        # subgraph extraction starts immediately, overlapping the next
        # chunk's detection — the upstream pipeline_worker behaviour.
        chunks = _chunk_plan(duration_sec)
        segments_ckpt_path = checkpoints / SEGMENTS_CHECKPOINT_FILENAME
        cached_chunks = await asyncio.to_thread(
            _load_checkpoint,
            segments_ckpt_path,
            job.source_checksum,
        )
        chunk_segments: dict[str, Any] = (
            dict(cached_chunks) if isinstance(cached_chunks, Mapping) else {}
        )
        semaphore = asyncio.Semaphore(SUBGRAPH_CONCURRENCY)
        work_root = Path(
            tempfile.mkdtemp(prefix=f"source-memory-{job.task_id[:24]}-"),
        )
        macros: list[MacroEvent] = []
        subgraph_jobs: list[asyncio.Task[None]] = []
        try:
            macro_counter = 0
            for chunk_start, chunk_end in chunks:
                chunk_key = f"{chunk_start:.0f}-{chunk_end:.0f}"
                cached = chunk_segments.get(chunk_key)
                if isinstance(cached, list) and cached:
                    segments = [
                        (float(pair[0]), float(pair[1])) for pair in cached
                    ]
                else:
                    segments = await asyncio.to_thread(
                        _detect_segments_sync,
                        local_path,
                        chunk_start,
                        chunk_end,
                    )
                    chunk_segments[chunk_key] = [
                        [start, end] for start, end in segments
                    ]
                    await asyncio.to_thread(
                        _write_checkpoint,
                        segments_ckpt_path,
                        job.source_checksum,
                        chunk_segments,
                    )
                chunk_macros = []
                for start, end in segments:
                    chunk_macros.append(
                        MacroEvent(
                            macro_id=f"macro_{macro_counter:04d}",
                            label=f"scene_{macro_counter:04d}",
                            time_range=[start, end],
                        ),
                    )
                    macro_counter += 1
                _merge_asr_into_macros(chunk_macros, transcript)
                macros.extend(chunk_macros)
                subgraph_jobs.extend(
                    asyncio.create_task(
                        self._extract_subgraph(
                            macro,
                            local_path,
                            work_root,
                            semaphore,
                            subgraph_ckpt_dir,
                            job.source_checksum,
                        ),
                    )
                    for macro in chunk_macros
                )
            logger.info(
                "source memory P1 done: task=%s macros=%d chunks=%d",
                job.task_id,
                len(macros),
                len(chunks),
            )
            if subgraph_jobs:
                await asyncio.gather(*subgraph_jobs)
        except BaseException:
            for pending in subgraph_jobs:
                pending.cancel()
            if subgraph_jobs:
                await asyncio.gather(*subgraph_jobs, return_exceptions=True)
            raise
        finally:
            await asyncio.to_thread(shutil.rmtree, work_root, True)
        extracted = sum(
            1
            for macro in macros
            if macro.subgraph
            and (macro.subgraph.entities or macro.subgraph.micro_events)
        )
        logger.info(
            "source memory P2 done: task=%s subgraphs=%d/%d",
            job.task_id,
            extracted,
            len(macros),
        )
        # Quality gate: a memory whose subgraphs all failed would only
        # serve fallback aggregations; fail the build instead of
        # persisting an unusable graph.
        if macros and extracted == 0:
            raise RuntimeError(
                "subgraph extraction failed for every macro segment",
            )

        # Phase 3: text-only aggregation via the configured VLM backend.
        async def call_llm(prompt: str) -> str:
            return await vlm_model.chat_completion(
                [{"type": "text", "text": prompt}],
                temperature=0.3,
                max_tokens=AGGREGATION_MAX_TOKENS,
            )

        root, supers, macro_rels, super_rels = await aggregate_hierarchy(
            macros,
            call_llm,
        )
        memory = HierarchicalGraphMemory(
            video_key=job.index_id,
            video_path=str(local_path),
            root=root,
            super_events=supers,
            macro_events=macros,
            macro_relations=macro_rels,
            super_relations=super_rels,
        )

        nodes = memory.get_all_nodes()
        vectors: np.ndarray | None = None
        if nodes and model_config.is_embedding_configured():
            embedded = await embedding_model.embed(
                [str(node["text"]) for node in nodes],
            )
            vectors = np.asarray(embedded, dtype=np.float32)
        elif nodes:
            logger.warning(
                "embedding not configured; persisting BM25-only text "
                "index for task=%s",
                job.task_id,
            )
        index_obj = EmbeddingIndex()
        index_obj.build(nodes, vectors)

        # Outer-VLM review of the projection drafts (the WT6 contract:
        # drafts enter the index surfaces only after review).
        draft_projection = SourceMemoryProjection(
            indexId=job.index_id,
            summary=self._projection_summary(memory),
            semanticEntries=self._projection_entries(memory),
        )
        projection = await self._review_projection(draft_projection)

        output = await asyncio.to_thread(
            self._persist_artifacts_sync,
            job,
            memory,
            index_obj,
            len(nodes),
            projection,
        )
        # Final artifacts are durable — the stage checkpoints have served
        # their purpose and must not shadow a future rebuild.
        await asyncio.to_thread(shutil.rmtree, checkpoints, True)
        await asyncio.to_thread(
            self.executions.append_attempt,
            job.project_id,
            job.task_id,
            event_id=f"{attempt_id}-succeeded",
            attempt_id=attempt_id,
            status=TaskAttemptStatus.SUCCEEDED,
            output=output,
            output_refs=[str(output["graphPath"])],
        )
        logger.info(
            "source memory build succeeded: task=%s macros=%d supers=%d "
            "nodes=%d",
            job.task_id,
            len(macros),
            len(supers),
            len(nodes),
        )

    def _existing_ref(
        self,
        job: SourceMemoryBuildJob,
    ) -> SourceMemoryRef | None:
        """Valid persisted artifacts for this build job, if any."""
        try:
            project_root = self.services.projects.project_root(
                job.project_id,
            )
        except Exception:  # pylint: disable=broad-except
            return None
        return load_memory_ref(
            project_root,
            job.index_id,
            job.source_checksum,
        )

    async def _index_transcript(
        self,
        job: SourceMemoryBuildJob,
    ) -> tuple[bool, list[dict[str, float | str]]]:
        """ASR availability and transcript records (seconds) from the
        published index."""
        from services.source_analysis import source_analysis_service

        try:
            index = await asyncio.to_thread(
                source_analysis_service(self.services).load,
                job.project_id,
                job.asset_id,
                job.index_id,
            )
        except Exception as error:  # pylint: disable=broad-except
            logger.warning(
                "source memory could not reload index transcript: %s",
                error,
            )
            return False, []
        asr_coverage = index.coverage.get("asr")
        available = (
            asr_coverage is not None and asr_coverage.mode == "available"
        )
        return available, [
            {
                "start_sec": segment.start_ms / 1000.0,
                "end_sec": segment.end_ms / 1000.0,
                "text": segment.text,
            }
            for segment in index.transcript
        ]

    async def _resolve_transcript(
        self,
        job: SourceMemoryBuildJob,
        local_path: Path,
        checkpoints: Path,
    ) -> list[dict[str, float | str]]:
        """ASR transcript for the build, billed at most once.

        Reuses the transcript the published index already carries
        (single billing, consistent text); transcribes only when the
        index never produced the ASR modality, checkpointing the billed
        result so a resumed build never pays again. Available-but-empty
        coverage (a silent source) is a legitimate final state and must
        not be billed again."""
        asr_available, index_transcript = await self._index_transcript(job)
        if asr_available:
            return index_transcript
        if not model_config.get_asr_api_key():
            return []
        ckpt_path = checkpoints / TRANSCRIPT_CHECKPOINT_FILENAME
        cached = await asyncio.to_thread(
            _load_checkpoint,
            ckpt_path,
            job.source_checksum,
        )
        if isinstance(cached, list):
            return [
                {
                    "start_sec": float(record["start_sec"]),
                    "end_sec": float(record["end_sec"]),
                    "text": str(record["text"]),
                }
                for record in cached
                if isinstance(record, Mapping)
            ]
        transcript: list[dict[str, float | str]] = []
        try:
            result = await asr_model.transcribe(local_path.as_uri())
            transcript = [
                {
                    "start_sec": segment.start_ms / 1000.0,
                    "end_sec": segment.end_ms / 1000.0,
                    "text": segment.text,
                }
                for segment in result.segments
            ]
        except Exception as error:  # pylint: disable=broad-except
            logger.warning(
                "source memory ASR failed (non-fatal): %s",
                error,
            )
            return []
        await asyncio.to_thread(
            _write_checkpoint,
            ckpt_path,
            job.source_checksum,
            transcript,
        )
        return transcript

    async def _extract_subgraph(
        self,
        macro: MacroEvent,
        local_path: Path,
        work_root: Path,
        semaphore: asyncio.Semaphore,
        checkpoint_dir: Path,
        source_checksum: str,
    ) -> None:
        # Resume path: a durable per-macro payload means this VLM call
        # was already billed — apply it and never call again.
        ckpt_path = checkpoint_dir / f"{macro.macro_id}.json"
        cached = await asyncio.to_thread(
            _load_checkpoint,
            ckpt_path,
            source_checksum,
        )
        if isinstance(cached, dict):
            apply_subgraph_payload(macro, cached)
            return
        async with semaphore:
            start, end = macro.time_range
            clip_path = work_root / f"{macro.macro_id}.mp4"
            try:
                await asyncio.to_thread(
                    _clip_segment_for_transport_sync,
                    local_path,
                    clip_path,
                    start,
                    end,
                )
            except Exception as error:  # pylint: disable=broad-except
                logger.warning(
                    "source memory clip failed for %s: %s",
                    macro.macro_id,
                    error,
                )
                macro.subgraph = Subgraph(macro_id=macro.macro_id)
                return
            prompt = (
                build_segment_context(macro) + SUBGRAPH_CONSTRUCTION_PROMPT
            )
            content = [
                vlm_model.multimodal_media_part(
                    clip_path.as_uri(),
                    "video",
                    fps=_segment_fps(end - start),
                ),
                {"type": "text", "text": prompt},
            ]
            payload: dict[str, Any] | None = None
            for attempt in range(SUBGRAPH_RETRIES + 1):
                try:
                    response = await vlm_model.chat_completion(
                        content,
                        temperature=0.7,
                        max_tokens=SUBGRAPH_MAX_TOKENS,
                    )
                    candidate = extract_json(response)
                    if isinstance(candidate, dict):
                        payload = candidate
                        break
                except Exception as error:  # pylint: disable=broad-except
                    logger.warning(
                        "source memory subgraph %s attempt %d failed: %s",
                        macro.macro_id,
                        attempt + 1,
                        error,
                    )
            try:
                clip_path.unlink(missing_ok=True)
            except OSError:
                pass
            if payload is None:
                macro.subgraph = Subgraph(macro_id=macro.macro_id)
                return
            # Persist before applying: apply_subgraph_payload mutates
            # the payload's relative times in place.
            await asyncio.to_thread(
                _write_checkpoint,
                ckpt_path,
                source_checksum,
                payload,
            )
            apply_subgraph_payload(macro, payload)

    async def _review_projection(
        self,
        draft: SourceMemoryProjection,
    ) -> SourceMemoryProjection:
        """Outer-VLM review of the projection drafts.

        Returns the reviewed projection (``review`` set). On any failure
        the drafts are kept without a review verdict and are therefore
        never merged into the index surfaces (fail-close).
        """
        # Stable per-draft IDs let the server, not the model, own the
        # authoritative time windows: the reviewer may only edit text,
        # tags and confidence or drop entries. Unknown/duplicated IDs or
        # any startMs/endMs drift fail the review closed.
        drafts_by_id = {
            f"entry-{position}": entry
            for position, entry in enumerate(draft.semantic_entries)
        }
        payload = {
            "summary": draft.summary,
            "semanticEntries": [
                {
                    "entryId": entry_id,
                    **entry.model_dump(mode="json", by_alias=True),
                }
                for entry_id, entry in drafts_by_id.items()
            ],
        }
        prompt = PROJECTION_REVIEW_PROMPT + json.dumps(
            payload,
            ensure_ascii=False,
        )
        try:
            response = await vlm_model.chat_completion(
                [{"type": "text", "text": prompt}],
                temperature=0.2,
                max_tokens=PROJECTION_REVIEW_MAX_TOKENS,
            )
            candidate = extract_json(response)
            reviewed_entries: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            for raw in candidate["semanticEntries"]:
                entry_id = str(raw.get("entryId") or "")
                original = drafts_by_id.get(entry_id)
                if original is None:
                    raise ValueError(
                        f"review invented an unknown entry: {entry_id!r}",
                    )
                if entry_id in seen_ids:
                    raise ValueError(
                        f"review duplicated entry {entry_id!r}",
                    )
                seen_ids.add(entry_id)
                if (
                    int(raw.get("startMs", -1)) != original.start_ms
                    or int(raw.get("endMs", -1)) != original.end_ms
                ):
                    raise ValueError(
                        f"review changed the time window of {entry_id!r}",
                    )
                reviewed_entries.append(
                    {
                        "text": raw["text"],
                        "tags": raw["tags"],
                        # The draft owns the authoritative window.
                        "startMs": original.start_ms,
                        "endMs": original.end_ms,
                        "confidence": raw["confidence"],
                    },
                )
            reviewed = SourceMemoryProjection.model_validate(
                {
                    "indexId": draft.index_id,
                    "summary": candidate["summary"],
                    "semanticEntries": reviewed_entries,
                    "review": {
                        "status": "approved",
                        "model": model_config.get_vlm_model_name(),
                        "reviewedAt": datetime.now(UTC)
                        .isoformat()
                        .replace("+00:00", "Z"),
                    },
                },
            )
            return reviewed
        except Exception as error:  # pylint: disable=broad-except
            logger.warning(
                "projection review failed (drafts stay unreviewed): %s",
                error,
            )
            return draft

    def _persist_artifacts_sync(
        self,
        job: SourceMemoryBuildJob,
        memory: HierarchicalGraphMemory,
        index_obj: EmbeddingIndex,
        node_count: int,
        projection: SourceMemoryProjection,
    ) -> dict[str, Any]:
        project_root = self.services.projects.project_root(job.project_id)
        directory = memory_dir(project_root, job.index_id)
        directory.mkdir(parents=True, exist_ok=True)
        graph_path = directory / GRAPH_FILENAME
        embeddings_path = directory / EMBEDDINGS_FILENAME
        memory.save(str(graph_path))
        index_obj.save(str(embeddings_path))
        # np.savez appends .npz when missing; normalize the artifact name.
        appended = directory / f"{EMBEDDINGS_FILENAME}.npz"
        if appended.exists():
            os.replace(appended, embeddings_path)
        built_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        projection_path = directory / PROJECTION_FILENAME
        tmp = projection_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                projection.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, projection_path)
        meta = {
            "indexId": job.index_id,
            "assetId": job.asset_id,
            "assetVersionId": job.asset_version_id,
            "sourceChecksum": job.source_checksum,
            "builtAt": built_at,
            "macroCount": len(memory.macro_events),
            "superCount": len(memory.super_events),
            "nodeCount": node_count,
            "graphPath": GRAPH_FILENAME,
            "embeddingsPath": EMBEDDINGS_FILENAME,
        }
        meta_path = directory / META_FILENAME
        tmp = meta_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, meta_path)
        relative = directory.relative_to(project_root).as_posix()
        return {
            "analysisVersionId": job.index_id,
            "macroCount": len(memory.macro_events),
            "superCount": len(memory.super_events),
            "nodeCount": node_count,
            "graphPath": f"{relative}/{GRAPH_FILENAME}",
            "embeddingsPath": f"{relative}/{EMBEDDINGS_FILENAME}",
            "builtAt": built_at,
        }

    @staticmethod
    def _projection_summary(memory: HierarchicalGraphMemory) -> str:
        root = memory.root
        parts = [part for part in (root.title, root.description) if part]
        return "\n\n".join(parts) or "(memory summary unavailable)"

    @staticmethod
    def _projection_entries(
        memory: HierarchicalGraphMemory,
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for super_event in memory.super_events:
            if len(super_event.time_range) < 2:
                continue
            start_ms = max(0, int(super_event.time_range[0] * 1000))
            end_ms = int(super_event.time_range[1] * 1000)
            if end_ms <= start_ms:
                continue
            text = super_event.label
            if super_event.description:
                text = f"{super_event.label}: {super_event.description}"
            tags = [
                str(item.get("name", ""))
                if isinstance(item, dict)
                else str(item)
                for item in super_event.key_entities
            ]
            tags = [tag for tag in tags if tag] or ["memory"]
            entries.append(
                {
                    "text": text,
                    "tags": tags[:8],
                    "startMs": start_ms,
                    "endMs": end_ms,
                    "confidence": 0.6,
                },
            )
        return entries

    # -- recovery ------------------------------------------------------------

    def recover_interrupted(self) -> None:
        """Converge or resume interrupted builds; never replay billed work.

        A build cut while RUNNING is closed as FAILED. It is re-queued
        when complete artifacts are already durable (the follow-up
        attempt converges without new model calls) or when stage
        checkpoints exist (the follow-up attempt resumes and only spends
        on the remaining macros — within the original authorization's
        estimate); otherwise it stays FAILED and a rebuild requires a
        fresh commit/authorization. QUEUED tasks resume their
        authorization wait as before.
        """
        for project_id in self._list_project_ids():
            try:
                tasks = self.executions.list_tasks(project_id)
            except Exception:  # pylint: disable=broad-except
                continue
            for task in tasks:
                if task.kind is not TaskKind.SOURCE_MEMORY_BUILD:
                    continue
                if task.status is TaskStatus.RUNNING:
                    task = self._close_interrupted(task)
                    if task.status is not TaskStatus.FAILED:
                        continue
                    job = self._job_from_task(task)
                    if job is None or (
                        self._existing_ref(job) is None
                        and not self._has_checkpoint(job)
                    ):
                        logger.warning(
                            "source memory build %s interrupted without "
                            "durable artifacts or checkpoints; not "
                            "retried automatically",
                            task.task_id,
                        )
                        continue
                    try:
                        task = self.executions.transition_task(
                            task.project_id,
                            task.task_id,
                            expected_status=TaskStatus.FAILED,
                            status=TaskStatus.QUEUED,
                        )
                    except (ExecutionStateConflict, RecordNotFoundError):
                        continue
                if task.status is TaskStatus.QUEUED:
                    job = self._job_from_task(task)
                    if job is not None:
                        self._spawn(job)

    def _list_project_ids(self) -> list[str]:
        try:
            return [
                summary.project_id for summary in self.services.projects.list()
            ]
        except Exception:  # pylint: disable=broad-except
            return []

    def _has_checkpoint(self, job: SourceMemoryBuildJob) -> bool:
        """Durable stage checkpoints matching this build job exist."""
        try:
            project_root = self.services.projects.project_root(
                job.project_id,
            )
        except Exception:  # pylint: disable=broad-except
            return False
        return has_build_checkpoint(
            project_root,
            job.index_id,
            job.source_checksum,
        )

    def _close_interrupted(self, task: TaskRecord) -> TaskRecord:
        """Close the attempt left RUNNING by a restart as FAILED."""
        try:
            attempts = self.executions.list_attempts(
                task.project_id,
                task.task_id,
            )
            if not attempts:
                return task
            open_attempt = attempts[-1]
            self.executions.append_attempt(
                task.project_id,
                task.task_id,
                event_id=f"{open_attempt.attempt_id}-interrupted",
                attempt_id=open_attempt.attempt_id,
                status=TaskAttemptStatus.FAILED,
                error={
                    "code": "MEMORY_BUILD_INTERRUPTED",
                    "message": "runtime restarted during the memory build",
                },
            )
            return self.executions.get_task(
                task.project_id,
                task.task_id,
            )
        except (ExecutionStateConflict, RecordNotFoundError):
            return task

    @staticmethod
    def _job_from_task(task: TaskRecord) -> SourceMemoryBuildJob | None:
        metadata = task.metadata
        index_id = str(metadata.get("analysisVersionId") or "")
        local_path = str(metadata.get("localPath") or "")
        checksum = str(metadata.get("sourceChecksum") or "")
        version_id = str(metadata.get("assetVersionId") or "")
        target_ref = str(metadata.get("targetRef") or "")
        duration = metadata.get("durationMs")
        required = (index_id, local_path, checksum, version_id)
        if not all(required) or not target_ref.startswith("asset:"):
            return None
        if not isinstance(duration, int):
            return None
        authorization_id = metadata.get("authorizationId")
        return SourceMemoryBuildJob(
            project_id=task.project_id,
            task_id=task.task_id,
            authorization_id=(
                str(authorization_id) if authorization_id else None
            ),
            index_id=index_id,
            asset_id=target_ref.partition(":")[2],
            asset_version_id=version_id,
            source_checksum=checksum,
            duration_ms=duration,
            local_path=local_path,
        )

    # -- query path ----------------------------------------------------------

    async def query_memory(  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
        self,
        *,
        project_id: str,
        logical_asset_id: str,
        query_type: str,
        query: str | None = None,
        node_types: list[str] | None = None,
        macro_id: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        top_k: int | None = None,
        min_cosine: float | None = None,
        max_results: int | None = None,
        scope: str = "source",
    ) -> dict[str, Any]:
        if query_type not in QUERY_TYPES:
            raise ValidationError(
                f"unknown query_type: {query_type}; expected one of "
                f"{', '.join(QUERY_TYPES)}",
            )
        if scope not in ("source", "project"):
            raise ValidationError(
                f"unknown scope: {scope}; expected source or project",
            )
        prefix_assets: dict[str, str] | None = None
        if scope == "project":
            # Merged cross-source memory: per-source timelines are
            # unrelated, so time-window queries stay per-source.
            if query_type == "by_time":
                raise ValidationError(
                    "by_time 只支持 scope=source：各素材的时间轴互不相关",
                )
            toolkit, prefix_assets = await self._merged_toolkit_for(
                project_id,
            )
            analysis_version_id = None
        else:
            from services.source_analysis import source_analysis_service

            index = await asyncio.to_thread(
                source_analysis_service(self.services).load,
                project_id,
                logical_asset_id,
            )
            if index.memory_ref is None:
                return {
                    "ok": True,
                    "available": False,
                    "assetId": logical_asset_id,
                    "reason": (
                        "该素材尚未构建长素材记忆；构建在素材理解完成后自动" "排队，需要执行授权通过后才会生成。"
                    ),
                }
            project_root = self.services.projects.project_root(project_id)
            graph_path = project_root / index.memory_ref.graph_path
            embeddings_path = project_root / index.memory_ref.embeddings_path
            toolkit = await self._toolkit_for(graph_path, embeddings_path)
            analysis_version_id = index.id
        top = max(1, min(int(top_k or 10), 50))
        query_text = (query or "").strip()
        if query_type in {
            "search_nodes",
            "search_ocr",
            "search_asr",
            "enumerate",
        }:
            if not query_text:
                raise ValidationError(f"{query_type} 查询需要 query 参数")
        query_embedding = None
        if query_type in {
            "search_nodes",
            "search_ocr",
            "search_asr",
            "enumerate",
        }:
            query_embedding = await self._embed_query(query_text)

        if query_type == "summary":
            result: Any = toolkit.get_summary()
        elif query_type == "super_events":
            result = toolkit.get_super_events()
        elif query_type == "macro_events":
            filter_id = (macro_id or "").strip()
            # Merged-memory super ids carry a source prefix
            # ("s1_super_01"), so match the marker anywhere.
            if "super_" in filter_id:
                result = toolkit.get_macro_events(super_id=filter_id)
            else:
                result = toolkit.get_macro_events()
        elif query_type == "subgraph":
            if not macro_id:
                raise ValidationError("subgraph 查询需要 macro_id 参数")
            result = toolkit.get_subgraph(macro_id)
        elif query_type == "search_nodes":
            result = toolkit.search_nodes(
                query_text,
                top_k=top,
                node_types=node_types,
                query_embedding=query_embedding,
            )
        elif query_type == "search_ocr":
            result = toolkit.search_ocr_text(
                query_text,
                top_k=top,
                query_embedding=query_embedding,
            )
        elif query_type == "search_asr":
            result = toolkit.search_asr_text(
                query_text,
                top_k=top,
                query_embedding=query_embedding,
            )
        elif query_type == "enumerate":
            # min_cosine/max_results follow the upstream enumerate
            # protocol: lower min_cosine and retry when the list looks
            # undercounted.
            floor = 0.5 if min_cosine is None else float(min_cosine)
            floor = max(0.0, min(floor, 1.0))
            cap = 120 if max_results is None else int(max_results)
            cap = max(1, min(cap, 300))
            result = toolkit.enumerate_events(
                query_text,
                min_cosine=floor,
                max_results=cap,
                node_types=node_types,
                query_embedding=query_embedding,
            )
        else:  # by_time
            if start_ms is None or end_ms is None or end_ms <= start_ms:
                raise ValidationError(
                    "by_time 查询需要有效的 start_ms/end_ms 半开区间",
                )
            result = toolkit.search_by_time(
                start_sec=start_ms / 1000.0,
                end_sec=end_ms / 1000.0,
            )
        payload: dict[str, Any] = {
            "ok": True,
            "available": True,
            "assetId": logical_asset_id,
            "analysisVersionId": analysis_version_id,
            "queryType": query_type,
            "scope": scope,
            "result": result,
            "hitWindowsMs": _collect_hit_windows(
                toolkit,
                result,
                prefix_assets,
            ),
        }
        if payload["hitWindowsMs"]:
            payload["verifyHint"] = (
                "命中窗口是记忆索引的候选结论；用于剪辑选段前，请对每个"
                "拟采纳的窗口调用 observe_source_clip 回原片核验。"
            )
        if prefix_assets is not None:
            payload["sources"] = [
                {"prefix": prefix, "assetId": asset_id}
                for prefix, asset_id in sorted(prefix_assets.items())
            ]
        return payload

    @staticmethod
    async def _embed_query(query_text: str) -> np.ndarray | None:
        try:
            vectors = await embedding_model.embed([query_text])
        except Exception as error:  # pylint: disable=broad-except
            logger.warning(
                "query embedding unavailable, BM25-only search: %s",
                error,
            )
            return None
        return np.asarray(vectors[0], dtype=np.float32)

    async def _toolkit_for(
        self,
        graph_path: Path,
        embeddings_path: Path,
    ) -> MemoryToolkit:
        key = str(graph_path)
        try:
            mtime = graph_path.stat().st_mtime
        except OSError as error:
            raise ValidationError(
                f"graph memory 文件不可用: {graph_path.name}",
            ) from error
        cached = self._toolkits.get(key)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        async with self._toolkits_lock:
            cached = self._toolkits.get(key)
            if cached is not None and cached[0] == mtime:
                return cached[1]
            toolkit = await asyncio.to_thread(
                _load_toolkit_sync,
                graph_path,
                embeddings_path,
            )
            self._toolkits[key] = (mtime, toolkit)
            return toolkit

    async def _merged_toolkit_for(
        self,
        project_id: str,
    ) -> tuple[MemoryToolkit, dict[str, str]]:
        """Merged toolkit over every built memory in the project.

        The merge is virtual (query-time, mtime-cached): graph payloads
        are ID-prefixed per source and concatenated, embedding matrices
        are stacked when every source has a usable, dimension-compatible
        ``embeddings.npz``; otherwise retrieval degrades to a BM25-only
        index over the merged nodes. Returns the toolkit plus the
        prefix→logical-asset map used to attribute hits.
        """
        project_root = self.services.projects.project_root(project_id)
        project = await asyncio.to_thread(
            lambda: self.services.projects.read(project_id).project,
        )
        entries = await asyncio.to_thread(
            list_built_memories,
            project_root,
            project,
        )
        if not entries:
            raise ValidationError(
                "scope=project 需要项目内至少一个已构建的长素材记忆",
            )
        fingerprint_parts: list[tuple[str, float]] = []
        for _, index_id, _ in entries:
            graph_path = memory_dir(project_root, index_id) / GRAPH_FILENAME
            try:
                fingerprint_parts.append(
                    (str(graph_path), graph_path.stat().st_mtime),
                )
            except OSError as error:
                raise ValidationError(
                    f"graph memory 文件不可用: {graph_path.name}",
                ) from error
        fingerprint = tuple(fingerprint_parts)
        cached = self._merged_toolkits.get(project_id)
        if cached is not None and cached[0] == fingerprint:
            return cached[1], cached[2]
        async with self._toolkits_lock:
            cached = self._merged_toolkits.get(project_id)
            if cached is not None and cached[0] == fingerprint:
                return cached[1], cached[2]
            toolkit, prefix_assets = await asyncio.to_thread(
                _load_merged_toolkit_sync,
                project_root,
                entries,
            )
            self._merged_toolkits[project_id] = (
                fingerprint,
                toolkit,
                prefix_assets,
            )
            return toolkit, prefix_assets


def _load_toolkit_sync(
    graph_path: Path,
    embeddings_path: Path,
) -> MemoryToolkit:
    memory = HierarchicalGraphMemory.load(str(graph_path))
    index = EmbeddingIndex()
    try:
        index.load(str(embeddings_path))
    except Exception as error:  # pylint: disable=broad-except
        # Degraded retrieval: a missing or corrupt .npz must not disable
        # the memory — rebuild the sparse BM25 index from the graph nodes
        # and serve text-only search (dense cosine stays off).
        logger.warning(
            "embeddings artifact unusable (%s); rebuilding BM25-only "
            "index from %s",
            error,
            graph_path.name,
        )
        index = EmbeddingIndex()
        index.build(memory.get_all_nodes(), None)
    return MemoryToolkit(memory, index)


def _load_merged_toolkit_sync(
    project_root: Path,
    entries: list[tuple[str, str, str]],
) -> tuple[MemoryToolkit, dict[str, str]]:
    """Build one merged toolkit from every built per-source memory.

    Dense vectors survive the merge only when every source contributes a
    loadable ``embeddings.npz`` of the same dimension (mixed embedding
    configurations degrade the merged index to BM25-only — per-source
    queries keep their own dense index either way).
    """
    prefixed_payloads: list[tuple[str, dict]] = []
    prefix_assets: dict[str, str] = {}
    merged_nodes: list[dict] = []
    matrices: list[np.ndarray] = []
    dense_ok = True
    for position, (logical_asset_id, index_id, _) in enumerate(entries):
        prefix = f"s{position + 1}"
        prefix_assets[prefix] = logical_asset_id
        directory = memory_dir(project_root, index_id)
        payload = json.loads(
            (directory / GRAPH_FILENAME).read_text(encoding="utf-8"),
        )
        prefix_graph_payload(payload, prefix)
        prefixed_payloads.append((prefix, payload))
        if not dense_ok:
            continue
        source_index = EmbeddingIndex()
        try:
            source_index.load(str(directory / EMBEDDINGS_FILENAME))
        except Exception as error:  # pylint: disable=broad-except
            logger.warning(
                "merged memory: embeddings for %s unusable (%s); "
                "degrading to BM25-only",
                index_id,
                error,
            )
            dense_ok = False
            continue
        if source_index.embeddings is None or not source_index.nodes:
            dense_ok = False
            continue
        if (
            matrices
            and matrices[0].shape[1] != source_index.embeddings.shape[1]
        ):
            logger.warning(
                "merged memory: embedding dimensions differ across "
                "sources; degrading to BM25-only",
            )
            dense_ok = False
            continue
        prefix_index_nodes(source_index.nodes, prefix)
        merged_nodes.extend(source_index.nodes)
        matrices.append(np.asarray(source_index.embeddings))
    memory = HierarchicalGraphMemory.from_payload(
        merged_graph_payload(prefixed_payloads),
    )
    index = EmbeddingIndex()
    if dense_ok and matrices:
        index.build(merged_nodes, np.vstack(matrices))
    else:
        index.build(memory.get_all_nodes(), None)
    return MemoryToolkit(memory, index), prefix_assets


def _collect_hit_windows(
    toolkit: MemoryToolkit,
    result: Any,
    prefix_assets: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Macro time windows (ms) for every macro hit inside a query result.

    For merged (scope=project) results each window also carries the
    ``assetId`` resolved from its macro-id source prefix, so callers can
    verify against the right original media."""
    macro_ids: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            candidate = value.get("macro_id")
            if isinstance(candidate, str) and candidate:
                macro_ids.append(candidate)
            parent = value.get("parent_macro")
            if isinstance(parent, Mapping):
                nested = parent.get("macro_id")
                if isinstance(nested, str) and nested:
                    macro_ids.append(nested)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(result)
    windows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in macro_ids:
        if candidate in seen:
            continue
        seen.add(candidate)
        # pylint: disable-next=protected-access
        macro = toolkit._macro_map.get(candidate)
        if macro is None or len(macro.time_range) < 2:
            continue
        window: dict[str, Any] = {
            "macroId": candidate,
            "startMs": int(macro.time_range[0] * 1000),
            "endMs": int(macro.time_range[1] * 1000),
        }
        if prefix_assets:
            prefix = candidate.partition("_")[0]
            asset_id = prefix_assets.get(prefix)
            if asset_id:
                window["assetId"] = asset_id
        windows.append(window)
    return windows


# ── prompt guidance ─────────────────────────────────────────────────────────

_MEMORY_GUIDANCE_AVAILABLE = """\
## 长素材记忆（query_source_memory）

本次委派的素材已构建层次图记忆（Root → SuperEvent → MacroEvent → 子图节点，\
ID 形如 super_01 / macro_0003），可用 `query_source_memory` 工具按台词、语义或\
时间精确定位片段：

- 先用 `summary` / `super_events` 建立全局认知，再用 `macro_events`（可传 \
super_id 过滤）缩小范围；
- 台词线索用 `search_asr`，屏幕文字用 `search_ocr`（两者是分离索引，不要拿 \
`search_nodes` 查台词/屏幕文字原文），事件/实体语义用 `search_nodes`，\
计数/枚举类问题用 `enumerate`，已知时间段用 `by_time`；
- **检索文本写法**：`query` 用陈述句描述目标内容，不要写问句（写“主角在厨房\
做饭”，不写“主角在哪里做饭？”）；多目标/多选项问题只取各选项共享的信息作为\
检索词，排除彼此分歧的细节；
- 命中后用 `subgraph` 下钻目标 macro 查看事件、实体与关系细节；典型配方是 \
1 次 search + 1-2 次 subgraph，不要反复提交措辞相近的同一查询；一种索引搜不到\
就换索引类型或换措辞，而不是重试原询；
- **计数协议**：必须用 `enumerate` 逐条数显式命中，不要拿 `search_nodes` 的 \
top-k 估数；若怀疑漏计，调低 `minCosine`（默认 0.5）并换措辞重试，合并相邻重复\
项后再回原片核验边界条目；
- 项目内有多个已构建记忆的长素材时，可传 `scope=project` 跨素材检索（结果 ID 带\
来源前缀，`hitWindowsMs` 附 assetId；`by_time` 不支持跨素材）；
- 记忆永远是粗粒度且可能不准的：不要直接拿 SuperEvent 摘要作答，也永远不要跳过\
查询凭印象作答；返回的 `hitWindowsMs` 是候选时间窗，结论必须回到原片窄窗核验：\
对每个拟采纳的窗口调用 `observe_source_clip`（question 带上待验证的结论本身），\
确认内容一致后才可写入素材理解或回复；核验不通过的窗口不得采纳。"""

_MEMORY_GUIDANCE_UNAVAILABLE = """\
## 长素材记忆

本次委派的素材尚无层次图记忆（未达到时长阈值或构建未完成）。\
`query_source_memory` 会返回 available=false；此时按常规流程直接观察原生媒体。"""


def memory_guidance_for_targets(
    project_root: Path | None,
    project: Any,
    target_refs: list[str] | tuple[str, ...] | None,
) -> str:
    """Render the memory_guidance prompt block for a delegation."""
    if project_root is None or project is None:
        return _MEMORY_GUIDANCE_UNAVAILABLE
    for target_ref in target_refs or ():
        kind, _, identifier = str(target_ref).partition(":")
        if kind != "asset" or not identifier:
            continue
        try:
            if has_built_memory(project_root, project, identifier):
                return _MEMORY_GUIDANCE_AVAILABLE
        except Exception:  # pylint: disable=broad-except
            continue
    return _MEMORY_GUIDANCE_UNAVAILABLE


# ── service registry ────────────────────────────────────────────────────────

_SERVICES: dict[str, SourceMemoryService] = {}


def source_memory_service(services: Any) -> SourceMemoryService:
    key = str(services.root)
    instance = _SERVICES.get(key)
    if instance is None or instance.services is not services:
        instance = SourceMemoryService(services)
        _SERVICES[key] = instance
    return instance


def clear_source_memory_service_registry() -> None:
    _SERVICES.clear()


def recover_interrupted_source_memory(services: Any) -> None:
    """Startup hook: converge builds interrupted by a restart."""
    source_memory_service(services).recover_interrupted()


__all__ = [
    "MEMORY_BUILD_THRESHOLD_MS",
    "QUERY_TYPES",
    "SOURCE_MEMORY_OPERATION",
    "SourceMemoryBuildJob",
    "SourceMemoryProjection",
    "SourceMemorySemanticDraft",
    "SourceMemoryService",
    "clear_source_memory_service_registry",
    "has_built_memory",
    "load_memory_ref",
    "memory_build_threshold_ms",
    "memory_dir",
    "memory_guidance_for_targets",
    "recover_interrupted_source_memory",
    "source_memory_service",
]
