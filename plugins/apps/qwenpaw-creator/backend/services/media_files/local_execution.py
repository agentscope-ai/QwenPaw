# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=consider-using-with,raise-missing-from,too-many-branches
# pylint: disable=too-many-statements,unused-argument,too-many-return-statements
"""File-native local video execution for edit and composition commands.

The service freezes one ``project.json`` snapshot, resolves every input through
its ``IndexedFile`` and immutable version record, persists Run/Task/Attempt
facts, and executes an injectable runner in
``<project>/runtime/task-work/<task-id>`` without holding Project or Runtime
locks.  A successful output is published through :class:`AssetFileStore` and
then indexed and selected by one Project commit.  Late cancelled or stale
outputs remain immutable but unindexed and are recorded in Runtime quarantine.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
import concurrent.futures
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import math
import mimetypes
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Protocol, TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from domain.enums import (
    CreatorCommandType,
    SpecialistRole,
    SpecialistRunStatus,
    TaskKind,
    TaskStatus,
)
from domain.errors import (
    ConflictError,
    NotFoundError,
    StorageIntegrityError,
    ValidationError,
)
from services.media_files.overlay import (
    PET_OS_VIBES,
    render_interview_summary_overlay,
    render_pet_os_overlay,
)
from services.media_files.motion_engine import full_engine_digest
from services.media_files.motion_overlay import (
    PreparedMotionLayer,
    caption_layout_error,
    composite_motion_layers,
    prepare_motion_layer,
    probe_motion_document,
    render_motion_overlay,
)
from services.media_files.beat_grid import (
    BeatGridUnavailable,
    extract_beat_grid,
)
from services.media_files.motion_templates import render_caption_template
from services.media_files.transitions import (
    SUPPORTED_XFADE_KINDS,
    TransitionClip,
    TransitionJoin,
    build_transition_filter_chain,
    normalize_transition_kind,
)
from services.project_files.assets import (
    AssetAlreadyExists,
    AssetFileError,
    AssetFileStore,
)
from services.project_files.models import (
    ArtifactSlot,
    ArtifactVersion,
    ArtifactVersionRenderSource,
    AudioCreation,
    EditCreation,
    ElementOutputRenderSource,
    I2VCreation,
    IndexedFile,
    MotionClipCreation,
    OverlayCreation,
    Project,
    R2VCreation,
    S2VCreation,
    SourceVersionRenderSource,
    T2VCreation,
    Timeline,
    TimelineElement,
    TransitionCreation,
)
from services.media_files.element_adapter import (
    find_timeline_element,
    selected_element_output,
)
from services.media_files.review_admission import (
    assert_media_review_admission,
    media_review_policy,
)
from services.render_review.review import schedule_render_review
from services.project_files.remote_cache import (
    public_source_url,
    resolve_remote_cache,
)
from services.project_files.store import ProjectSnapshot
from services.runtime_files.atomic_store import (
    AtomicJsonRecordStore,
    canonical_json_bytes,
)
from services.runtime_files.errors import RecordNotFoundError
from services.runtime_files.execution_models import (
    SpecialistRunRecord,
    TaskAttemptStatus,
    TaskRecord,
)
from services.runtime_files.execution_store import (
    ExecutionPayloadConflict,
    ExecutionStateConflict,
    ProjectExecutionStore,
)
from services.runtime_files.models import ChangeOrigin, ReviewPolicy
from services.runtime_files.media_probe import MediaProbeError, probe_media
from services.runtime_files.runtime_dependencies import resolve_ffmpeg

# pylint: disable=no-name-in-module
from utils.logger import setup_logger
from utils.remote_download import download_remote_file

# pylint: enable=no-name-in-module

if TYPE_CHECKING:
    from services.project_files.facade import CreatorFileServices


logger = setup_logger("services.media_files.local_execution")

_RETIRED_MOTION_MOTIFS = (
    "speed_lines",
    "side_eye",
    "sassy_cat",
    "surprised_cat",
    "happy_cat",
    "confused_cat",
)

_LOCAL_MEDIA_COMMANDS = frozenset(
    {
        CreatorCommandType.EXECUTE_EDIT,
        CreatorCommandType.COMPOSE_FINAL_VIDEO,
    },
)
_MAX_VIDEO_BYTES = 4 * 1024 * 1024 * 1024
# Motion layers burned per ffmpeg pass: enough to cover a typical caption
# stack in one encode while keeping the filter graph and PNG-sequence
# input memory bounded.
_MOTION_BURN_BATCH_SIZE = 8
# Finished-segment cache: re-renders of an unchanged segment (same source
# content, trims, canvas and overlay stack) are byte-for-byte identical, so
# an edit to one Element re-renders only its own segment.
_SEGMENT_CACHE_MAX_ITEMS = 96
# Renderer behaviour version for cached segments; bump on any semantic
# change to segment rendering or overlay burning.
_SEGMENT_CACHE_VERSION = 2


@dataclass(frozen=True, slots=True)
class _SegmentRender:
    """Outcome of rendering one timeline segment."""

    path: Path
    duration: float
    warnings: tuple[str, ...]


_DEFAULT_FFMPEG_TIMEOUT_SECONDS = 15 * 60.0
_DEFAULT_FFMPEG_TERMINATION_GRACE_SECONDS = 5.0
# Original-footage volume while a Timeline audio Element (narration) plays;
# ~-9dB keeps ambience audible without competing with the voice.
_DUCK_VOLUME = 0.35
# Beat-snapped xfades must keep a perceptible blend; below this the join
# effectively degrades to a cut and the snap is skipped instead.
_MIN_SNAPPED_BLEND_SECONDS = 0.05


def _merge_windows(
    windows: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Merge overlapping [start, end) windows so ducking applies once."""

    merged: list[tuple[float, float]] = []
    for start, end in sorted(windows):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


@dataclass(frozen=True, slots=True)
class LocalMediaInput:
    version_id: str
    file_id: str | None
    checksum: str
    media_type: str
    path: Path
    source_ref: str
    start_seconds: float | None = None
    end_seconds: float | None = None
    duration_seconds: float | None = None
    original_sound: str = "preserve"
    location: Mapping[str, Any] | None = None
    overlays: tuple[Mapping[str, Any], ...] = ()
    motions: tuple[Mapping[str, Any], ...] = ()
    # A full-canvas motion document that IS the segment's picture (pure
    # motion-graphics cut): the renderer paints it over an opaque base
    # for the whole span instead of cutting from a media file.
    motion_clip: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class LocalMediaExecutionSpec:
    command: CreatorCommandType
    target_ref: str
    task_id: str
    work_dir: Path
    output_path: Path
    inputs: tuple[LocalMediaInput, ...]
    transitions: tuple[dict[str, Any], ...]
    audio_plan: Mapping[str, Any] | str
    expected_duration_seconds: float | None
    canvas_size: tuple[int, int]
    on_element_done: Callable[[int, int], None] | None = None
    audio_tracks: tuple[Mapping[str, Any], ...] = ()
    color_grade: str = ""


def _input_render_element_ids(item: LocalMediaInput) -> frozenset[str]:
    ids: set[str] = set()
    if item.source_ref.startswith("element:"):
        ids.add(item.source_ref.removeprefix("element:"))
    else:
        ids.add(f"input:{item.version_id}")
    for overlay in item.overlays:
        if isinstance(overlay, Mapping):
            element_id = overlay.get("element_id")
            if isinstance(element_id, str) and element_id:
                ids.add(element_id)
    for motion in item.motions:
        element_id = motion.get("element_id")
        if isinstance(element_id, str) and element_id:
            ids.add(element_id)
    return frozenset(ids)


def _render_element_total(inputs: Sequence[LocalMediaInput]) -> int:
    return len(
        {
            element_id
            for item in inputs
            for element_id in _input_render_element_ids(item)
        },
    )


class LocalMediaRunner(Protocol):
    """Runner boundary.  Implementations write exactly ``spec.output_path``."""

    async def render(self, spec: LocalMediaExecutionSpec) -> Mapping[str, Any]:
        ...


# Unified colour-grade presets applied to the whole composited cut.
# Every preset must keep skin tones natural: gentle eq lifts plus a small
# colour-balance shift, never LUT-strength stylisation.
_COLOR_GRADE_FILTERS: dict[str, str] = {
    # 明亮、温暖、清新：家庭 Vlog 默认暖色基调。
    "warm_bright": (
        "eq=brightness=0.02:saturation=1.12:gamma=1.03,"
        "colorbalance=rm=0.03:gm=0.01:bm=-0.04:rh=0.02:bh=-0.02"
    ),
    # 冷静通透：科技/城市内容的冷色基调。
    "clean_cool": (
        "eq=brightness=0.01:saturation=1.05:gamma=1.02,"
        "colorbalance=rm=-0.02:bm=0.04:bh=0.02"
    ),
    # 电影感：压暗部、轻微去饱和。
    "cinematic": (
        "eq=brightness=-0.01:saturation=0.96:contrast=1.08:gamma=0.98,"
        "colorbalance=sm=-0.03:bh=-0.02"
    ),
}


class FfmpegLocalMediaRunner:
    """Default local ffmpeg runner with no global ``/generated`` authority."""

    def __init__(
        self,
        executable: str | None = None,
        *,
        timeout_seconds: float = _DEFAULT_FFMPEG_TIMEOUT_SECONDS,
        termination_grace_seconds: float = (
            _DEFAULT_FFMPEG_TERMINATION_GRACE_SECONDS
        ),
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if (
            not math.isfinite(termination_grace_seconds)
            or termination_grace_seconds <= 0
        ):
            raise ValueError(
                "termination_grace_seconds must be finite and positive",
            )
        self.executable = executable or resolve_ffmpeg() or "ffmpeg"
        self.timeout_seconds = float(timeout_seconds)
        self.termination_grace_seconds = float(termination_grace_seconds)

    async def render(self, spec: LocalMediaExecutionSpec) -> Mapping[str, Any]:
        self._validate_supported_directives(spec)
        overlay_warnings = await asyncio.to_thread(self._render_sync, spec)
        metadata: dict[str, Any] = {"runner": "ffmpeg"}
        if overlay_warnings:
            metadata["overlayWarnings"] = overlay_warnings
        return {
            "media_type": "video/mp4",
            "duration_seconds": spec.expected_duration_seconds,
            "metadata": metadata,
        }

    def _render_sync(self, spec: LocalMediaExecutionSpec) -> list[str]:
        if not spec.inputs:
            raise ValidationError("本地媒体执行至少需要一个输入")
        concat_inputs: list[Path] = []
        segment_durations: list[float] = []
        overlay_warnings: list[str] = []
        input_element_ids = tuple(
            _input_render_element_ids(item) for item in spec.inputs
        )
        remaining_element_occurrences = Counter(
            element_id
            for element_ids in input_element_ids
            for element_id in element_ids
        )
        total_elements = len(remaining_element_occurrences)
        tail_trims, joins_by_pair = self._transition_directives(spec)
        self._snap_transitions_to_beats(spec, tail_trims, joins_by_pair)
        if spec.command in (
            CreatorCommandType.EXECUTE_EDIT,
            CreatorCommandType.COMPOSE_FINAL_VIDEO,
        ) or any(
            item.start_seconds is not None
            or item.location is not None
            or item.overlays
            or item.motions
            for item in spec.inputs
        ):
            segment_dir = _ensure_real_directory_chain(
                spec.work_dir,
                "segments",
            )
            concurrency = self._segment_concurrency(len(spec.inputs))
            outcomes: dict[int, _SegmentRender] = {}
            done_signals = 0

            def _report_done(index: int) -> None:
                # Progress ticks fire in completion order; the completed
                # count is monotonic because every tick only decrements
                # the shared occurrence counter. Thread-safety note: this
                # closure runs exclusively on the coordinating thread (the
                # serial loop, or the as_completed() consumer) — worker
                # threads only execute _render_one_segment and never touch
                # the counter, so no lock is needed here.
                if spec.on_element_done is None:
                    return
                for element_id in input_element_ids[index]:
                    remaining_element_occurrences[element_id] -= 1
                completed_elements = sum(
                    remaining == 0
                    for remaining in remaining_element_occurrences.values()
                )
                spec.on_element_done(completed_elements, total_elements)

            if concurrency <= 1 or len(spec.inputs) <= 1:
                for index, item in enumerate(spec.inputs):
                    outcomes[index] = self._render_one_segment(
                        spec,
                        index,
                        item,
                        segment_dir=segment_dir,
                        tail_trims=tail_trims,
                    )
                    done_signals += 1
                    _report_done(index)
            else:
                # Segments share no state (each burns its own overlay
                # stack onto its own file); the only serialized resource
                # is the capture worker, which queues internally.
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=concurrency,
                ) as pool:
                    futures = {
                        pool.submit(
                            self._render_one_segment,
                            spec,
                            index,
                            item,
                            segment_dir=segment_dir,
                            tail_trims=tail_trims,
                        ): index
                        for index, item in enumerate(spec.inputs)
                    }
                    try:
                        for future in concurrent.futures.as_completed(
                            futures,
                        ):
                            index = futures[future]
                            outcomes[index] = future.result()
                            done_signals += 1
                            _report_done(index)
                    except BaseException:
                        for pending_future in futures:
                            pending_future.cancel()
                        raise
            del done_signals
            for index in range(len(spec.inputs)):
                outcome = outcomes[index]
                concat_inputs.append(outcome.path)
                segment_durations.append(outcome.duration)
                overlay_warnings.extend(outcome.warnings)
        else:
            concat_inputs.extend(item.path for item in spec.inputs)
        joins = self._resolve_segment_joins(spec, joins_by_pair)
        if any(join.effective_blend() > 0 for join in joins) and len(
            segment_durations,
        ) == len(concat_inputs):
            self._compose_with_transitions(
                concat_inputs,
                segment_durations,
                joins,
                spec.output_path,
                work_dir=spec.work_dir,
                canvas_size=spec.canvas_size,
            )
        else:
            self._concat(
                concat_inputs,
                spec.output_path,
                work_dir=spec.work_dir,
            )
        if spec.audio_tracks:
            self._mix_audio_tracks(spec)
        grade_warning = self._apply_color_grade(spec)
        if grade_warning:
            overlay_warnings.append(grade_warning)
        return overlay_warnings

    @staticmethod
    def _snap_transitions_to_beats(
        spec: LocalMediaExecutionSpec,
        tail_trims: dict[str, float],
        joins: dict[tuple[str, str], TransitionJoin],
    ) -> None:
        """Beat-sync (WT-B5): land each xfade's resolution moment on a beat.

        The overlap a transition consumes is fixed by the Timeline
        (blend + tail trim = overlap), but the split between the two is a
        render-side degree of freedom: shifting δ from trim to blend moves
        the moment the incoming shot fully takes over (xfade end) by δ
        while the chain offsets after the join and the total duration stay
        exactly on the Timeline end. Snapping therefore never retimes the
        committed cut layout. Requires a BGM track; degradation (no
        librosa, unreadable audio) is declared in the log, never silent.
        """
        if not any(join.effective_blend() > 0 for join in joins.values()):
            return
        track = max(
            (
                item
                for item in spec.audio_tracks
                if item.get("path")
                and float(item.get("max_duration_seconds") or 0.0) > 0
            ),
            key=lambda item: float(item["max_duration_seconds"]),
            default=None,
        )
        if track is None:
            return
        try:
            grid = extract_beat_grid(Path(track["path"]))
        except BeatGridUnavailable as error:
            logger.info("转场 beat-sync 跳过（已声明降级）: %s", error)
            return
        except Exception as error:  # noqa: BLE001 - snapping is best-effort
            logger.warning("节拍网格提取失败，转场不吸附: %s", error)
            return
        if not grid.beats_ms:
            return
        music_offset = float(track.get("offset_seconds") or 0.0)
        durations: list[float] = []
        for item in spec.inputs:
            if item.start_seconds is not None and item.end_seconds is not None:
                raw = item.end_seconds - item.start_seconds
            elif item.duration_seconds is not None:
                raw = item.duration_seconds
            else:
                return  # boundaries cannot be predicted — leave unsnapped
            durations.append(raw - tail_trims.get(item.source_ref, 0.0))
        accumulated = durations[0]
        for index in range(1, len(spec.inputs)):
            pair = (
                spec.inputs[index - 1].source_ref,
                spec.inputs[index].source_ref,
            )
            join = joins.get(pair)
            blend = join.effective_blend() if join is not None else 0.0
            if join is not None and blend > 0:
                from_ref = pair[0]
                trim = tail_trims.get(from_ref, 0.0)
                local_ms = round((accumulated - music_offset) * 1000)
                delta = (grid.snap_ms(local_ms) - local_ms) / 1000
                new_blend = blend + delta
                new_trim = trim - delta
                if (
                    delta
                    and new_trim >= 0
                    and _MIN_SNAPPED_BLEND_SECONDS
                    <= new_blend
                    < min(durations[index - 1], durations[index])
                ):
                    tail_trims[from_ref] = new_trim
                    durations[index - 1] += delta
                    joins[pair] = TransitionJoin(
                        kind=join.kind,
                        blend_seconds=new_blend,
                    )
                    accumulated += delta
                    blend = new_blend
            accumulated = accumulated - blend + durations[index]

    @staticmethod
    def _transition_directives(
        spec: LocalMediaExecutionSpec,
    ) -> tuple[dict[str, float], dict[tuple[str, str], TransitionJoin]]:
        """Project spec.transitions into per-input tail trims and adjacent
        pair join modes."""

        tail_trims: dict[str, float] = {}
        joins: dict[tuple[str, str], TransitionJoin] = {}
        for transition in spec.transitions:
            from_ref = f"element:{transition.get('fromElementId')}"
            to_ref = f"element:{transition.get('toElementId')}"
            raw_trim = transition.get("tail_trim_ms", 0)
            raw_duration = transition.get("duration_ms", 0)
            trim_ms = (
                float(raw_trim)
                if isinstance(raw_trim, (int, float))
                and not isinstance(raw_trim, bool)
                else 0.0
            )
            duration_ms = (
                float(raw_duration)
                if isinstance(raw_duration, (int, float))
                and not isinstance(raw_duration, bool)
                else 0.0
            )
            if trim_ms > 0:
                tail_trims[from_ref] = (
                    tail_trims.get(from_ref, 0.0) + trim_ms / 1000
                )
            joins[(from_ref, to_ref)] = TransitionJoin(
                kind=str(transition.get("kind") or "cut"),
                blend_seconds=duration_ms / 1000,
            )
        return tail_trims, joins

    @staticmethod
    def _resolve_segment_joins(
        spec: LocalMediaExecutionSpec,
        joins_by_pair: Mapping[tuple[str, str], TransitionJoin],
    ) -> list[TransitionJoin]:
        return [
            joins_by_pair.get(
                (
                    spec.inputs[index - 1].source_ref,
                    spec.inputs[index].source_ref,
                ),
                TransitionJoin(),
            )
            for index in range(1, len(spec.inputs))
        ]

    def _apply_color_grade(
        self,
        spec: LocalMediaExecutionSpec,
    ) -> str | None:
        """Re-encode the composited cut through one unified grade preset.

        Grading runs last (after concat and audio mixing) so a single
        deterministic pass colours every segment, transition and burned
        overlay identically. Unknown preset names degrade to a warning:
        losing the grade must never lose the cut.
        """

        grade = (spec.color_grade or "").strip()
        if not grade:
            return None
        video_filter = _COLOR_GRADE_FILTERS.get(grade)
        if video_filter is None:
            return f"未知的统一调色预设 {grade!r}，已跳过调色；可用预设: " + ", ".join(
                sorted(_COLOR_GRADE_FILTERS),
            )
        graded = spec.work_dir / "graded.mp4"
        self._run(
            [
                "-y",
                "-i",
                os.fspath(spec.output_path),
                "-vf",
                video_filter,
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
                os.fspath(graded),
            ],
            cwd=spec.work_dir,
        )
        graded.replace(spec.output_path)
        return None

    def _mix_audio_tracks(self, spec: LocalMediaExecutionSpec) -> None:
        """Mix Timeline audio Elements into the composed video.

        The video stream is stream-copied; each track is trimmed to its span,
        gain/pan adjusted, delayed to its Timeline offset, then mixed with the
        composed video's own audio (when present) without renormalization.
        While a narration track plays, the original footage audio is ducked so
        the two never fight for attention.
        """

        premix = spec.work_dir / "premix.mp4"
        os.replace(spec.output_path, premix)
        arguments: list[str] = ["-y", "-i", os.fspath(premix)]
        filters: list[str] = []
        labels: list[str] = []
        duck_windows: list[tuple[float, float]] = []
        for index, track in enumerate(spec.audio_tracks):
            arguments += ["-i", os.fspath(track["path"])]
            chain = [f"[{index + 1}:a]aformat=channel_layouts=stereo"]
            duration = float(track.get("max_duration_seconds") or 0.0)
            if duration > 0:
                chain.append(f"atrim=0:{duration:.6f}")
            gain = float(track.get("gain_db") or 0.0)
            if gain:
                chain.append(f"volume={gain:.3f}dB")
            pan = float(track.get("pan") or 0.0)
            if pan:
                left = max(0.0, min(1.0, 1.0 - pan))
                right = max(0.0, min(1.0, 1.0 + pan))
                chain.append(
                    f"pan=stereo|c0={left:.3f}*c0|c1={right:.3f}*c1",
                )
            offset = float(track.get("offset_seconds") or 0.0)
            delay_ms = int(round(offset * 1000))
            if delay_ms > 0:
                chain.append(f"adelay={delay_ms}:all=1")
            if duration > 0:
                duck_windows.append((offset, offset + duration))
            label = f"[mix{index}]"
            filters.append(",".join(chain) + label)
            labels.append(label)
        if self._probe_has_audio(premix):
            base_chain = ["[0:a]aformat=channel_layouts=stereo"]
            for start, end in _merge_windows(duck_windows):
                base_chain.append(
                    f"volume={_DUCK_VOLUME}:enable="
                    f"'between(t,{start:.3f},{end:.3f})'",
                )
            filters.append(",".join(base_chain) + "[base]")
            labels.insert(0, "[base]")
        if len(labels) == 1:
            mixed = labels[0]
        else:
            filters.append(
                f"{''.join(labels)}amix=inputs={len(labels)}"
                ":duration=longest:normalize=0[aout]",
            )
            mixed = "[aout]"
        # Cap audio at the composed video duration so a long narration cannot
        # extend the container past the final frame.
        final_label = mixed
        if spec.expected_duration_seconds:
            filters.append(
                f"{mixed}atrim=0:{spec.expected_duration_seconds:.6f}[afinal]",
            )
            final_label = "[afinal]"
        self._run(
            [
                *arguments,
                "-filter_complex",
                ";".join(filters),
                "-map",
                "0:v",
                "-map",
                final_label,
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                os.fspath(spec.output_path),
            ],
            cwd=spec.work_dir,
        )

    def _probe_has_audio(self, path: Path) -> bool:
        try:
            return bool(
                probe_media(
                    os.fspath(path),
                    ffmpeg_path=self.executable,
                    timeout=min(self.timeout_seconds, 30.0),
                ).has_audio,
            )
        except MediaProbeError:
            # Fall back to anullsrc when probing fails, so we never
            # reference an audio track that does not exist.
            return False

    def _compose_with_transitions(
        self,
        segments: Sequence[Path],
        durations: Sequence[float],
        joins: Sequence[TransitionJoin],
        output: Path,
        *,
        work_dir: Path,
        canvas_size: tuple[int, int],
    ) -> None:
        """Compose the transition-bearing final video with one
        xfade/acrossfade filter chain."""

        clips = [
            TransitionClip(
                duration_seconds=duration,
                has_audio=self._probe_has_audio(path),
            )
            for path, duration in zip(segments, durations)
        ]
        try:
            chain = build_transition_filter_chain(
                clips,
                list(joins),
                canvas_size=canvas_size,
            )
        except ValueError as exc:
            raise ValidationError(f"转场布局无法合成: {exc}") from exc
        arguments: list[str] = ["-y"]
        for path in segments:
            arguments.extend(["-i", os.fspath(path)])
        arguments.extend(
            [
                "-filter_complex",
                chain,
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                os.fspath(output),
            ],
        )
        self._run(arguments, cwd=work_dir)

    @staticmethod
    def _normalized_location(
        raw: Mapping[str, Any] | None,
    ) -> dict[str, float]:
        defaults = {
            "x": 0.5,
            "y": 0.5,
            "width": 1.0,
            "height": 1.0,
            "anchor_x": 0.5,
            "anchor_y": 0.5,
            "rotation_degrees": 0.0,
            "opacity": 1.0,
        }
        if not isinstance(raw, Mapping):
            return defaults
        normalized = dict(defaults)
        for key, fallback in defaults.items():
            try:
                value = float(raw.get(key, fallback))
            except (TypeError, ValueError):
                value = fallback
            normalized[key] = value if math.isfinite(value) else fallback
        normalized["width"] = max(1e-6, normalized["width"])
        normalized["height"] = max(1e-6, normalized["height"])
        normalized["anchor_x"] = min(1.0, max(0.0, normalized["anchor_x"]))
        normalized["anchor_y"] = min(1.0, max(0.0, normalized["anchor_y"]))
        normalized["opacity"] = min(1.0, max(0.0, normalized["opacity"]))
        return normalized

    @classmethod
    def _placement_filter(
        cls,
        raw: Mapping[str, Any] | None,
        *,
        canvas_size: tuple[int, int],
        duration_seconds: float,
        freeze_duration: float = 0.0,
        freeze_audio: bool = False,
    ) -> str:
        """Build one anchor-based placement graph shared with the UI preview."""

        location = cls._normalized_location(raw)
        canvas_width, canvas_height = canvas_size
        box_width = max(2, round(canvas_width * location["width"]) // 2 * 2)
        box_height = max(2, round(canvas_height * location["height"]) // 2 * 2)
        anchor_x = round(box_width * location["anchor_x"])
        anchor_y = round(box_height * location["anchor_y"])
        padded_width = max(2, 2 * max(anchor_x, box_width - anchor_x))
        padded_height = max(2, 2 * max(anchor_y, box_height - anchor_y))
        pad_x = padded_width // 2 - anchor_x
        pad_y = padded_height // 2 - anchor_y
        radians = math.radians(location["rotation_degrees"])
        rotated_width = max(
            2,
            (
                math.ceil(
                    abs(padded_width * math.cos(radians))
                    + abs(padded_height * math.sin(radians)),
                )
                + 1
            )
            // 2
            * 2,
        )
        rotated_height = max(
            2,
            (
                math.ceil(
                    abs(padded_width * math.sin(radians))
                    + abs(padded_height * math.cos(radians)),
                )
                + 1
            )
            // 2
            * 2,
        )
        overlay_x = round(location["x"] * canvas_width - rotated_width / 2)
        overlay_y = round(location["y"] * canvas_height - rotated_height / 2)

        # Build the video filter chain
        video_filters = (
            f"[0:v]scale={box_width}:{box_height}:force_original_aspect_ratio=increase,"
            f"crop={box_width}:{box_height},setsar=1,format=rgba,"
            f"colorchannelmixer=aa={location['opacity']:.6f},"
            f"pad={padded_width}:{padded_height}:{pad_x}:{pad_y}:color=0x00000000,"
            f"rotate={location['rotation_degrees']:.6f}*PI/180:"
            f"ow={rotated_width}:oh={rotated_height}:c=none"
        )

        # Add tpad filter to freeze the last frame if needed
        if freeze_duration > 0:
            video_filters += (
                f",tpad=stop_mode=clone:stop_duration={freeze_duration:.6f}"
            )

        video_filters += "[fg]"

        # Build the filter chain
        filter_chain = (
            f"{video_filters};"
            f"color=c=black:s={canvas_width}x{canvas_height}:r=30:"
            f"d={duration_seconds:.6f}[bg];"
            f"[bg][fg]overlay={overlay_x}:{overlay_y}:shortest=1,format=yuv420p[outv]"
        )

        # Only pad audio when freezing a source that actually has a stream.
        if freeze_audio:
            filter_chain += f";[0:a]apad=pad_dur={freeze_duration:.6f}[a]"

        return filter_chain

    def _segment_concurrency(self, segment_count: int) -> int:
        """Parallel segment renders for one composition.

        Segments are independent (each owns its file and overlay stack);
        the ceiling keeps Chromium + ffmpeg peak memory bounded on a
        developer machine.  ``QWENPAW_SEGMENT_CONCURRENCY=1`` restores
        strictly serial rendering.
        """

        raw = os.environ.get("QWENPAW_SEGMENT_CONCURRENCY", "")
        try:
            configured = int(raw) if raw else 3
        except ValueError:
            configured = 3
        return max(1, min(configured, segment_count, os.cpu_count() or 1))

    def _segment_cache_key(
        self,
        spec: LocalMediaExecutionSpec,
        item: LocalMediaInput,
        *,
        segment_duration: float,
        freeze_duration: float,
    ) -> str | None:
        """Content identity of one finished (base + burned layers) segment.

        Every input that can change the segment's pixels or sound must
        appear here; the checksum identifies source bytes, motion/overlay
        projections identify burned layers by document checksum, and the
        engine digest salts the html_js frame renderer.  Returns ``None``
        when the item carries no stable content checksum.
        """

        if not item.checksum:
            return None
        try:
            payload = {
                "v": _SEGMENT_CACHE_VERSION,
                "checksum": item.checksum,
                "mediaType": item.media_type,
                "start": item.start_seconds,
                "end": item.end_seconds,
                "sourceDuration": item.duration_seconds,
                "segmentDuration": round(segment_duration, 6),
                "freeze": round(freeze_duration, 6),
                "canvas": list(spec.canvas_size),
                "location": item.location,
                "originalSound": item.original_sound,
                "overlays": [
                    _fingerprint_overlay(overlay) for overlay in item.overlays
                ],
                "motions": [
                    _fingerprint_motion(motion) for motion in item.motions
                ],
                "motionClip": (
                    _fingerprint_motion(item.motion_clip)
                    if item.motion_clip is not None
                    else None
                ),
                "engine": full_engine_digest(),
            }
            return hashlib.sha256(
                canonical_json_bytes(payload),
            ).hexdigest()
        except Exception:  # noqa: BLE001 - cache is best-effort only
            return None

    @staticmethod
    def _segment_cache_root() -> Path:
        root = Path(tempfile.gettempdir()) / "qwenpaw-segment-cache-v1"
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        return root

    def _restore_cached_segment(
        self,
        cache_key: str,
        segment: Path,
    ) -> tuple[str, ...] | None:
        """Copy one cached segment into place; returns its warnings."""

        entry = self._segment_cache_root() / f"{cache_key}.mp4"
        sidecar = entry.with_suffix(".json")
        if not entry.is_file():
            return None
        try:
            shutil.copy2(entry, segment)
            warnings: tuple[str, ...] = ()
            if sidecar.is_file():
                data = json.loads(sidecar.read_text(encoding="utf-8"))
                warnings = tuple(str(w) for w in (data.get("warnings") or []))
            entry.touch()  # LRU recency
            return warnings
        except Exception:  # noqa: BLE001 - fall back to a fresh render
            return None

    def _store_cached_segment(
        self,
        cache_key: str,
        segment: Path,
        warnings: Sequence[str],
    ) -> None:
        root = self._segment_cache_root()
        entry = root / f"{cache_key}.mp4"
        try:
            staged = entry.with_name(f"{entry.stem}.{os.getpid()}.tmp")
            shutil.copy2(segment, staged)
            staged.replace(entry)
            entry.with_suffix(".json").write_text(
                json.dumps({"warnings": list(warnings)}),
                encoding="utf-8",
            )
            self._prune_segment_cache(root)
        except Exception:  # noqa: BLE001 - cache is best-effort only
            return

    @staticmethod
    def _prune_segment_cache(root: Path) -> None:
        entries = sorted(
            root.glob("*.mp4"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for stale in entries[_SEGMENT_CACHE_MAX_ITEMS:]:
            stale.unlink(missing_ok=True)
            stale.with_suffix(".json").unlink(missing_ok=True)

    def _render_one_segment(
        self,
        spec: LocalMediaExecutionSpec,
        index: int,
        item: LocalMediaInput,
        *,
        segment_dir: Path,
        tail_trims: Mapping[str, float],
    ) -> _SegmentRender:
        """Render one timeline segment: base picture plus burned layers."""

        start_seconds = item.start_seconds or 0.0
        end_seconds = item.end_seconds
        if end_seconds is None:
            if item.duration_seconds is None:
                raise ValidationError(
                    "Edit Element 缺少可执行 source range",
                )
            end_seconds = start_seconds + item.duration_seconds
        # For a transition pair, the tail of the `from` segment that
        # the `to` segment covers is simply not rendered; the rest of
        # the overlap is consumed by the xfade blend.
        tail_trim = tail_trims.get(item.source_ref, 0.0)
        segment_duration = max(
            1 / 30,
            end_seconds - start_seconds - tail_trim,
        )

        # Calculate freeze duration if target exceeds source
        freeze_duration = 0.0
        if (
            item.duration_seconds is not None
            and item.start_seconds is not None
            and item.end_seconds is not None
        ):
            source_duration = item.duration_seconds
            target_duration = item.end_seconds - item.start_seconds
            if target_duration > source_duration:
                freeze_duration = target_duration - source_duration

        segment = segment_dir / f"{index:06d}.mp4"
        cache_key = self._segment_cache_key(
            spec,
            item,
            segment_duration=segment_duration,
            freeze_duration=freeze_duration,
        )
        if cache_key is not None:
            cached_warnings = self._restore_cached_segment(cache_key, segment)
            if cached_warnings is not None:
                return _SegmentRender(
                    segment,
                    segment_duration,
                    cached_warnings,
                )

        warnings: list[str] = []
        if item.motion_clip is not None:
            # A pure motion-graphics segment: the document paints
            # the whole picture, so the base is a silent opaque
            # canvas and the clip renders full-frame on top.
            self._render_motion_clip_segment(
                item,
                segment,
                canvas_size=spec.canvas_size,
                segment_duration=segment_duration,
                work_dir=spec.work_dir,
            )
        else:
            # A still image can carry a segment (pure motion-graphics
            # cuts render generated backdrops with overlays on top).
            # ffmpeg needs -loop 1 to keep emitting frames and -t to
            # bound the loop; seeking into a still is meaningless.
            is_still_image = item.duration_seconds is None and str(
                item.media_type or "",
            ).startswith("image/")
            # apad references [0:a]; sources without an audio stream
            # (common for generated R2V footage) must keep the optional
            # 0:a? mapping or ffmpeg rejects the whole filtergraph.
            freeze_audio = (
                freeze_duration > 0
                and not is_still_image
                and self._probe_has_audio(item.path)
            )
            placement_filter = self._placement_filter(
                item.location,
                canvas_size=spec.canvas_size,
                duration_seconds=segment_duration,
                freeze_duration=freeze_duration,
                freeze_audio=freeze_audio,
            )

            # Build FFmpeg arguments
            if is_still_image:
                ffmpeg_args = [
                    "-y",
                    "-loop",
                    "1",
                    "-framerate",
                    "30",
                    "-t",
                    f"{segment_duration:.6f}",
                    "-i",
                    os.fspath(item.path),
                ]
            else:
                ffmpeg_args = [
                    "-y",
                    "-ss",
                    f"{start_seconds:.6f}",
                    "-t",
                    f"{segment_duration:.6f}",
                    "-i",
                    os.fspath(item.path),
                ]
            ffmpeg_args.extend(
                [
                    "-filter_complex",
                    placement_filter,
                    "-map",
                    "[outv]",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-pix_fmt",
                    "yuv420p",
                ],
            )

            # Map audio if present
            if freeze_audio:
                ffmpeg_args.extend(["-map", "[a]"])
            else:
                ffmpeg_args.extend(["-map", "0:a?"])

            ffmpeg_args.extend(
                [
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    os.fspath(segment),
                ],
            )

            self._run(ffmpeg_args, cwd=spec.work_dir)
        # Text-free motion layers (variety frames, decorations) burn
        # first; caption cards burn on top so copy stays readable even
        # when a frame border crosses the caption box (variety-show
        # packaging puts 花字 on the frame, never under it).
        for warning in self._apply_motion_overlays(item, segment):
            warnings.append(
                f"{item.source_ref or item.version_id}: {warning}",
            )
        for warning in self._apply_overlay(item, segment):
            warnings.append(
                f"{item.source_ref or item.version_id}: {warning}",
            )
        if cache_key is not None:
            self._store_cached_segment(cache_key, segment, warnings)
        return _SegmentRender(segment, segment_duration, tuple(warnings))

    def _apply_overlay(
        self,
        item: LocalMediaInput,
        segment: Path,
    ) -> list[str]:
        """Burn every text overlay into one prepared segment.

        Overlays are applied sequentially; each reads the segment produced by
        the previous one so they stack in z_index order.
        """
        warnings: list[str] = []
        segment_duration = (
            item.end_seconds - item.start_seconds
            if item.start_seconds is not None and item.end_seconds is not None
            else item.duration_seconds
        )
        video_size: tuple[int, int] | None = None
        # Motion layers queue up and burn in one ffmpeg pass per batch, so
        # N captions cost one encode generation instead of N sequential
        # re-encodes.  A fixed-style fallback flushes the queue first so
        # stacking keeps strict z_index order.
        pending: list[
            tuple[
                PreparedMotionLayer,
                str | None,
                Mapping[str, Any],
                Mapping[str, Any] | None,
            ]
        ] = []

        def flush_pending() -> None:
            queue = list(pending)
            pending.clear()
            for start in range(0, len(queue), _MOTION_BURN_BATCH_SIZE):
                batch = queue[start : start + _MOTION_BURN_BATCH_SIZE]
                burned = segment.with_name(f"{segment.stem}-overlay.mp4")
                result = composite_motion_layers(
                    ffmpeg_path=self.executable,
                    input_path=segment,
                    output_path=burned,
                    layers=[layer for layer, _, _, _ in batch],
                )
                if result.success:
                    os.replace(burned, segment)
                    warnings.extend(err for _, err, _, _ in batch if err)
                    continue
                burned.unlink(missing_ok=True)
                # Degraded path: burn one by one so a single bad layer
                # cannot sink its whole batch; a still-failing layer drops
                # to the fixed style so caption copy never leaves the cut.
                for layer, err, fb_overlay, fb_location in batch:
                    single = composite_motion_layers(
                        ffmpeg_path=self.executable,
                        input_path=segment,
                        output_path=burned,
                        layers=[layer],
                    )
                    if single.success:
                        os.replace(burned, segment)
                        if err is not None:
                            warnings.append(err)
                        continue
                    burned.unlink(missing_ok=True)
                    self._burn_fixed_overlay(
                        fb_overlay,
                        segment,
                        video_size or self._probe_video_size(segment),
                        warnings,
                        f"{fb_overlay['kind']} 动效层合成失败，已回退固定样式: "
                        f"{single.error or '未知错误'}",
                        fb_location,
                    )

        for raw in item.overlays:
            overlay = self._normalized_overlay(raw, segment_duration)
            if overlay is None:
                continue
            if video_size is None:
                video_size = self._probe_video_size(segment)
            styled_error: str | None = None
            motion = overlay.get("motion")
            render_location = overlay.get("location")
            using_safe_motion = False
            if (
                isinstance(motion, Mapping)
                and str(motion.get("html") or "").strip()
                and not _motion_document_matches_text(
                    str(motion["html"]),
                    str(overlay.get("text") or ""),
                )
            ):
                motion = None
                styled_error = (
                    f"{overlay['kind']} 动效文档与当前文案不一致，" "已用回退样式渲染最新文案"
                )
            if (
                isinstance(motion, Mapping)
                and str(motion.get("html") or "").strip()
            ):
                safety_error = caption_layout_error(
                    render_location,
                    str(overlay.get("text") or ""),
                    video_size,
                )
                if safety_error is None:
                    location = render_location
                    width_ratio = (
                        float(location.get("width", 1.0))
                        if isinstance(location, Mapping)
                        else 1.0
                    )
                    height_ratio = (
                        float(location.get("height", 1.0))
                        if isinstance(location, Mapping)
                        else 1.0
                    )
                    probe = probe_motion_document(
                        str(motion["html"]),
                        doc_format=str(motion.get("format") or "html_css"),
                        box_width=max(160, round(video_size[0] * width_ratio)),
                        box_height=max(
                            90,
                            round(video_size[1] * height_ratio),
                        ),
                        ffmpeg_path=self.executable,
                    )
                    if not probe.ok:
                        safety_error = probe.error
                    elif probe.edge_contact > 0.02:
                        safety_error = "字幕卡内容触碰视口边缘，存在裁切风险"
                    elif probe.text_occlusion > 0.10:
                        safety_error = "字幕文字被卡片内的图标或装饰遮挡"
                if safety_error is not None:
                    render_location = {
                        "x": 0.5,
                        "y": 0.88,
                        "width": 0.8,
                        "height": 0.18,
                        "anchor_x": 0.5,
                        "anchor_y": 0.5,
                        "opacity": 1.0,
                    }
                    motion = {
                        "html": render_caption_template(
                            str(overlay.get("text") or ""),
                            emotion=str(overlay.get("vibe") or "chill"),
                            box_width=0.8,
                            box_height=0.18,
                        ),
                        "fps": 24,
                        "loop": False,
                    }
                    using_safe_motion = True
                    styled_error = (
                        f"{overlay['kind']} 字幕动效未通过合成安全检查，"
                        f"已用统一安全动效模板渲染: {safety_error}"
                    )
            if (
                isinstance(motion, Mapping)
                and str(motion.get("html") or "").strip()
            ):
                prep = prepare_motion_layer(
                    ffmpeg_path=self.executable,
                    html=str(motion["html"]),
                    fps=min(60, max(8, int(motion.get("fps") or 24))),
                    loop=bool(motion.get("loop", True)),
                    video_size=video_size,
                    appear_at=overlay["appear_at"],
                    duration=overlay["duration"],
                    location=render_location,
                    viewport_inset=0.05,
                    doc_format=str(motion.get("format") or "html_css"),
                    # Caption cards may bleed background blocks off their
                    # box on purpose; readability is guarded by the
                    # design-time layout/occlusion/copy gates instead.
                    max_edge_contact=1.0,
                )
                if prep.layer is not None:
                    pending.append(
                        (prep.layer, styled_error, overlay, render_location),
                    )
                    continue
                if not using_safe_motion:
                    generated_error = prep.error or "未知错误"
                    render_location = {
                        "x": 0.5,
                        "y": 0.88,
                        "width": 0.8,
                        "height": 0.18,
                        "anchor_x": 0.5,
                        "anchor_y": 0.5,
                        "opacity": 1.0,
                    }
                    safe_prep = prepare_motion_layer(
                        ffmpeg_path=self.executable,
                        html=render_caption_template(
                            str(overlay.get("text") or ""),
                            emotion=str(overlay.get("vibe") or "chill"),
                            box_width=0.8,
                            box_height=0.18,
                        ),
                        fps=24,
                        loop=False,
                        video_size=video_size,
                        appear_at=overlay["appear_at"],
                        duration=overlay["duration"],
                        location=render_location,
                        viewport_inset=0.05,
                    )
                    if safe_prep.layer is not None:
                        pending.append(
                            (
                                safe_prep.layer,
                                f"{overlay['kind']} 生成样式渲染失败，"
                                f"已用统一安全动效模板渲染: {generated_error}",
                                overlay,
                                render_location,
                            ),
                        )
                        continue
                    styled_error = (
                        f"{overlay['kind']} 生成样式与安全动效模板均渲染失败，"
                        "已回退固定样式: "
                        f"{generated_error}; {safe_prep.error or '未知错误'}"
                    )
                else:
                    styled_error = (
                        f"{overlay['kind']} 安全动效模板渲染失败，"
                        f"已回退固定样式: {prep.error or '未知错误'}"
                    )
            # The fixed style stacks below any queued motion layers unless
            # the queue burns first, so flush before painting it.
            flush_pending()
            self._burn_fixed_overlay(
                overlay,
                segment,
                video_size,
                warnings,
                styled_error,
                render_location,
            )
        flush_pending()
        return warnings

    def _burn_fixed_overlay(
        self,
        overlay: Mapping[str, Any],
        segment: Path,
        video_size: tuple[int, int],
        warnings: list[str],
        styled_error: str | None,
        render_location: Mapping[str, Any] | None,
    ) -> None:
        """Burn one fixed-style caption; failure aborts the composition."""

        rendered = segment.with_name(f"{segment.stem}-overlay.mp4")
        if overlay["kind"] == "pet_os":
            result = render_pet_os_overlay(
                ffmpeg_path=self.executable,
                input_path=segment,
                output_path=rendered,
                text=overlay["text"],
                vibe=overlay["vibe"],
                video_size=video_size,
                appear_at=overlay["appear_at"],
                duration=overlay["duration"],
                location=render_location,
            )
        else:
            # Interview-summary card styling: reached by legacy inputs
            # frozen before overlay kinds were removed and by overlays
            # whose migrated presentation is vibe="summary".
            result = render_interview_summary_overlay(
                ffmpeg_path=self.executable,
                input_path=segment,
                output_path=rendered,
                text=overlay["text"],
                video_size=video_size,
                appear_at=overlay["appear_at"],
                duration=overlay["duration"],
                location=overlay.get("location"),
            )
        if not result.success:
            rendered.unlink(missing_ok=True)
            # The fixed template is the last carrier of the caption
            # copy: when it fails too, the final cut would silently
            # lose mandatory content, so the execution aborts and the
            # task fails into the rejection feedback loop.
            raise ValidationError(
                f"{overlay['kind']} 字幕渲染失败，已中止合成（台词内容不得从成片中"
                f"丢失）: {result.error or '未知错误'}",
            )
        os.replace(rendered, segment)
        if styled_error is not None:
            warnings.append(styled_error)

    def _apply_motion_overlays(
        self,
        item: LocalMediaInput,
        segment: Path,
    ) -> list[str]:
        """Burn every generated motion overlay into one prepared segment.

        A failed decoration has no fallback rendering: shipping the
        segment anyway would silently publish a final cut that lacks a
        committed overlay. The render error aborts the whole execution so
        the task fails and the rejection feedback loop can regenerate or
        drop the design instead.
        """

        warnings: list[str] = []
        video_size: tuple[int, int] | None = None
        layers: list[PreparedMotionLayer] = []
        for motion in item.motions:
            normalized = self._normalized_motion(item, motion)
            if normalized is None:
                continue
            if video_size is None:
                video_size = self._probe_video_size(segment)
            prep = prepare_motion_layer(
                ffmpeg_path=self.executable,
                html=normalized["html"],
                fps=normalized["fps"],
                loop=normalized["loop"],
                video_size=video_size,
                appear_at=normalized["appear_at"],
                duration=normalized["duration"],
                location=normalized.get("location"),
                viewport_inset=0.05,
                doc_format=normalized["format"],
            )
            if prep.layer is None:
                raise ValidationError(
                    f"motion overlay {normalized['element_id']} 渲染失败，"
                    "已中止合成（不发布缺少既定动效的成片）；请修复或移除该动效 "
                    f"Element 后重新合成: {prep.error or '未知错误'}",
                )
            layers.append(prep.layer)
        for start in range(0, len(layers), _MOTION_BURN_BATCH_SIZE):
            batch = layers[start : start + _MOTION_BURN_BATCH_SIZE]
            rendered = segment.with_name(f"{segment.stem}-motion.mp4")
            result = composite_motion_layers(
                ffmpeg_path=self.executable,
                input_path=segment,
                output_path=rendered,
                layers=batch,
            )
            if not result.success:
                rendered.unlink(missing_ok=True)
                raise ValidationError(
                    "motion overlay 合成失败，已中止合成（不发布缺少既定动效的"
                    f"成片）: {result.error or '未知错误'}",
                )
            os.replace(rendered, segment)
        return warnings

    def _render_motion_clip_segment(
        self,
        item: LocalMediaInput,
        segment: Path,
        *,
        canvas_size: tuple[int, int],
        segment_duration: float,
        work_dir: Path,
    ) -> None:
        """Rasterize one full-canvas motion document into a segment.

        The document paints the segment's whole picture, so a failed
        render aborts the execution: unlike a lost decoration there is
        no base footage to fall back to.
        """

        payload = item.motion_clip
        assert payload is not None
        html = str(payload.get("html") or "")
        if not html.strip():
            raise ValidationError(
                f"动效片段 {item.source_ref} 的文档为空，无法合成",
            )
        width, height = canvas_size
        base_args = [
            "-y",
            "-f",
            "lavfi",
            "-i",
            (
                f"color=c=black:s={width}x{height}:r=30"
                f":d={segment_duration:.6f}"
            ),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            os.fspath(segment),
        ]
        self._run(base_args, cwd=work_dir)
        rendered = segment.with_name(f"{segment.stem}-clip.mp4")
        result = render_motion_overlay(
            ffmpeg_path=self.executable,
            input_path=segment,
            output_path=rendered,
            html=html,
            fps=int(payload.get("fps") or 24),
            loop=bool(payload.get("loop", True)),
            video_size=canvas_size,
            appear_at=0.0,
            duration=segment_duration,
            location=None,
            doc_format=str(payload.get("format") or "html_css"),
            full_canvas=True,
        )
        if not result.success:
            rendered.unlink(missing_ok=True)
            raise ValidationError(
                f"动效片段 {item.source_ref} 渲染失败，已中止合成（纯动效片段没有可回退的"
                f"底层画面）: {result.error or '未知错误'}",
            )
        os.replace(rendered, segment)

    @staticmethod
    def _normalized_motion(
        item: LocalMediaInput,
        raw: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if not isinstance(raw, Mapping):
            return None
        html = str(raw.get("html") or "")
        if not html.strip():
            return None
        if any(
            f'data-motion-motif="{motif}"' in html
            or f"data-motion-motif='{motif}'" in html
            for motif in _RETIRED_MOTION_MOTIFS
        ):
            return None
        segment_duration = (
            item.end_seconds - item.start_seconds
            if item.start_seconds is not None and item.end_seconds is not None
            else item.duration_seconds
        )
        if segment_duration is None or not math.isfinite(segment_duration):
            return None
        try:
            appear_at = float(raw.get("appear_at", 0.0))
        except (TypeError, ValueError):
            appear_at = 0.0
        if not math.isfinite(appear_at):
            appear_at = 0.0
        appear_at = max(0.0, appear_at)
        if appear_at >= segment_duration:
            return None
        try:
            duration = float(raw.get("duration", segment_duration - appear_at))
        except (TypeError, ValueError):
            duration = segment_duration - appear_at
        if not math.isfinite(duration) or duration <= 0:
            duration = segment_duration - appear_at
        duration = min(duration, segment_duration - appear_at)
        # A cross-boundary overlay leaves only a sliver of itself on this
        # segment (transitions shift the cut points); an entrance animation
        # is still transparent there, so the truth gate would reject the
        # whole composite over frames nobody can see. Skip the sliver — the
        # neighbouring segment renders the overlay in full.
        if duration < 0.3:
            return None
        try:
            fps = int(raw.get("fps", 24))
        except (TypeError, ValueError):
            fps = 24
        return {
            "element_id": str(raw.get("element_id") or ""),
            "html": html,
            "format": str(raw.get("format") or "html_css"),
            "fps": min(60, max(8, fps)),
            "loop": bool(raw.get("loop", True)),
            "appear_at": appear_at,
            "duration": duration,
            "location": (
                dict(raw["location"])
                if isinstance(raw.get("location"), Mapping)
                else None
            ),
        }

    @staticmethod
    def _normalized_overlay(
        raw: Mapping[str, Any] | None,
        segment_duration: float | None,
    ) -> dict[str, Any] | None:
        if not isinstance(raw, Mapping):
            return None
        kind = str(raw.get("kind") or "").strip().casefold()
        text = str(raw.get("text") or "").strip()
        if kind not in {"pet_os", "interview_summary"} or not text:
            return None
        if segment_duration is None or not math.isfinite(segment_duration):
            return None
        try:
            appear_at = float(raw.get("appear_at", 0.0))
        except (TypeError, ValueError):
            appear_at = 0.0
        if not math.isfinite(appear_at):
            appear_at = 0.0
        appear_at = max(0.0, appear_at)
        if appear_at >= segment_duration:
            return None
        try:
            duration = float(raw.get("duration", segment_duration - appear_at))
        except (TypeError, ValueError):
            duration = segment_duration - appear_at
        if not math.isfinite(duration) or duration <= 0:
            duration = segment_duration - appear_at
        duration = min(duration, segment_duration - appear_at)
        vibe = str(raw.get("vibe") or "chill").strip().casefold()
        return {
            "kind": kind,
            "text": text,
            "vibe": vibe if vibe in PET_OS_VIBES else "chill",
            "appear_at": appear_at,
            "duration": duration,
            "location": (
                dict(raw["location"])
                if isinstance(raw.get("location"), Mapping)
                else None
            ),
            "motion": (
                dict(raw["motion"])
                if isinstance(raw.get("motion"), Mapping)
                else None
            ),
        }

    def _probe_video_size(self, path: Path) -> tuple[int, int]:
        try:
            metadata = probe_media(
                os.fspath(path),
                ffmpeg_path=self.executable,
                timeout=min(self.timeout_seconds, 30.0),
            )
            if metadata.width and metadata.height:
                return metadata.width, metadata.height
        except MediaProbeError:
            pass
        return 1280, 720

    @staticmethod
    def _validate_supported_directives(spec: LocalMediaExecutionSpec) -> None:
        unsupported_transitions: list[str] = []
        for transition in spec.transitions:
            kind = str(transition.get("kind") or "cut").strip().casefold()
            if kind != "cut" and kind not in SUPPORTED_XFADE_KINDS:
                unsupported_transitions.append(kind or "<empty>")
        if unsupported_transitions:
            raise ValidationError(
                "默认 ffmpeg runner 仅支持 cut/"
                + "/".join(sorted(SUPPORTED_XFADE_KINDS))
                + " 转场: "
                + ", ".join(unsupported_transitions),
            )

        unsupported_original_sound = sorted(
            {
                item.original_sound.strip()
                for item in spec.inputs
                if item.original_sound.strip().casefold()
                not in {"", "preserve"}
            },
        )
        if unsupported_original_sound:
            raise ValidationError(
                "默认 ffmpeg runner 尚不支持 original_sound 指令: "
                + ", ".join(unsupported_original_sound),
            )

        if isinstance(spec.audio_plan, Mapping):
            preserve_original = spec.audio_plan.get("preserve_original", True)
            instructions = [
                str(spec.audio_plan.get(key) or "").strip()
                for key in ("music_prompt", "voiceover", "notes")
            ]
            if preserve_original is not True or any(instructions):
                raise ValidationError(
                    "默认 ffmpeg runner 仅支持保留原声且无配乐、旁白或备注的 audio_plan",
                )
        elif str(spec.audio_plan or "").strip():
            # Planning agents record free-text audio ideas on the
            # composition (e.g. "upbeat background music").  The string form carries no
            # structured directive the local pipeline could execute, and
            # neither the UI nor any command lets users clear the field, so
            # failing here would dead-end COMPOSE_FINAL_VIDEO for every
            # agent-driven project.  Preserve the original audio and surface
            # the note in the log instead.
            logger.warning(
                "默认 ffmpeg runner 忽略自由文本 audio_plan（保留原声）: %s",
                str(spec.audio_plan).strip(),
            )

    def _concat(
        self,
        inputs: Sequence[Path],
        output: Path,
        *,
        work_dir: Path,
    ) -> None:
        manifest = work_dir / "concat.txt"
        manifest.write_text(
            "".join(f"file '{_ffconcat_path(path)}'\n" for path in inputs),
            encoding="utf-8",
        )
        # Segment AAC frame grids never line up exactly with their video
        # duration, so stream-copying audio through the concat demuxer
        # leaves sub-frame gaps at every joint. The mp4 muxer stretches
        # the packet before each gap to cover it, and browsers abort
        # decoding on such oversized packets — every seek past the first
        # joint then hangs. Video packets are unaffected and stay copied;
        # audio is re-concatenated from the decoded segments instead.
        audio_flags = [self._probe_has_audio(path) for path in inputs]
        if any(audio_flags):
            audio_labels: list[str] = []
            filter_parts: list[str] = []
            for index, (path, has_audio) in enumerate(
                zip(inputs, audio_flags),
            ):
                if has_audio:
                    audio_labels.append(f"[{index + 1}:a]")
                    continue
                duration = self._probe_duration_seconds(path)
                filter_parts.append(
                    "anullsrc=channel_layout=stereo:sample_rate=48000,"
                    f"atrim=duration={duration:.6f}[silent{index}]",
                )
                audio_labels.append(f"[silent{index}]")
            filter_parts.append(
                "".join(audio_labels)
                + f"concat=n={len(inputs)}:v=0:a=1,"
                + "aresample=async=1:first_pts=0[outa]",
            )
            self._run(
                [
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    os.fspath(manifest),
                    *(
                        argument
                        for path in inputs
                        for argument in ("-i", os.fspath(path))
                    ),
                    "-filter_complex",
                    ";".join(filter_parts),
                    "-map",
                    "0:v",
                    "-c:v",
                    "copy",
                    "-map",
                    "[outa]",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    os.fspath(output),
                ],
                cwd=work_dir,
            )
            return
        self._run(
            [
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                os.fspath(manifest),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                os.fspath(output),
            ],
            cwd=work_dir,
        )

    def _probe_duration_seconds(self, path: Path) -> float:
        try:
            duration = probe_media(
                os.fspath(path),
                ffmpeg_path=self.executable,
                timeout=min(self.timeout_seconds, 30.0),
            ).duration_seconds
        except MediaProbeError:
            duration = None
        return duration if duration and duration > 0 else 1 / 30

    def _run(self, arguments: Sequence[str], *, cwd: Path) -> None:
        try:
            process = subprocess.Popen(
                [self.executable, *arguments],
                cwd=cwd,
                # ffmpeg reads stdin by default; inheriting the service
                # process tty triggers SIGTTIN and suspends the process group
                # when running in the background, so detach explicitly.
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as exc:
            raise ValidationError("本机未安装 ffmpeg") from exc
        try:
            stdout, stderr = process.communicate(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            try:
                process.terminate()
            except OSError:
                pass
            try:
                process.communicate(timeout=self.termination_grace_seconds)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except OSError:
                    pass
                try:
                    process.communicate(timeout=self.termination_grace_seconds)
                except subprocess.TimeoutExpired:
                    # The child has already received the strongest portable
                    # signal.  Never turn cleanup into another unbounded wait.
                    pass
            raise ConflictError(
                f"ffmpeg 执行超时（{self.timeout_seconds:g} 秒）",
            ) from exc
        if process.returncode != 0:
            detail = (stderr or stdout or "ffmpeg failed")[-4000:]
            raise ConflictError(f"ffmpeg 执行失败: {detail}")


@dataclass(frozen=True, slots=True)
class FileLocalMediaExecutionResult:
    task_id: str
    run_id: str
    transaction_id: str
    artifact_version_id: str
    project_etag: str
    project_generation: int
    replayed: bool

    def command_response(self, command_id: str) -> dict[str, Any]:
        return {
            "commandId": command_id,
            "status": "APPLIED",
            "eventSeq": 0,
            "transactionId": self.transaction_id,
            "workingHead": self.project_etag,
        }


@dataclass(frozen=True, slots=True)
class _FrozenInput:
    version_id: str
    indexed: IndexedFile | None
    checksum: str
    source_ref: str
    media_type: str
    source_url: str | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None
    duration_seconds: float | None = None
    original_sound: str = "preserve"
    location: Mapping[str, Any] | None = None
    overlays: tuple[Mapping[str, Any], ...] = ()
    motions: tuple[Mapping[str, Any], ...] = ()
    motion_clip: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class _FrozenAudioTrack:
    """One enabled Timeline audio Element resolved to its source version."""

    element_id: str
    version_id: str
    indexed: IndexedFile | None
    checksum: str
    media_type: str
    source_url: str | None
    offset_seconds: float
    max_duration_seconds: float
    gain_db: float
    pan: float


@dataclass(frozen=True, slots=True)
class _ResolvedExecution:
    command: CreatorCommandType
    target_ref: str
    task_kind: TaskKind
    inputs: tuple[_FrozenInput, ...]
    transitions: tuple[dict[str, Any], ...]
    audio_plan: Mapping[str, Any] | str
    expected_duration_seconds: float | None
    canvas_size: tuple[int, int]
    slot_id: str
    slot_kind: str
    owner_ref: str
    artifact_name: str
    read_set: tuple[dict[str, Any], ...]
    source_selections: tuple[dict[str, Any], ...]
    audio_tracks: tuple[_FrozenAudioTrack, ...] = ()
    color_grade: str = ""


def _stable_id(prefix: str, project_id: str, key: str) -> str:
    digest = uuid5(
        NAMESPACE_URL,
        f"qwenpaw-creator:file-local-media:{prefix}:{project_id}:{key}",
    ).hex
    return f"{prefix}-{digest}"


def _fingerprint(value: Mapping[str, Any]) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def _target_id(target_ref: str, prefix: str) -> str:
    expected = f"{prefix}:"
    if not target_ref.startswith(expected) or not target_ref[len(expected) :]:
        raise ValidationError(f"targetRef 必须是 {expected}<id>")
    return target_ref[len(expected) :]


def _target_timeline(project: Project, target_ref: str) -> Timeline:
    """Resolve a timeline targetRef.

    Canonical Timeline IDs already carry the ``timeline:`` prefix (for
    example ``timeline:main``), so both ``timeline:timeline:main`` and the
    bare ID ``timeline:main`` must resolve to the same Timeline.
    """

    timeline_id = _target_id(target_ref, "timeline")
    timeline = project.timelines.items.get(timeline_id)
    if timeline is None:
        timeline = project.timelines.items.get(target_ref)
    if timeline is None:
        raise NotFoundError("Timeline 不存在")
    return timeline


def _canvas_size(aspect_ratio: str, resolution: str) -> tuple[int, int]:
    """Resolve Project display settings to one even-pixel render canvas."""

    try:
        width_part, height_part = aspect_ratio.split(":", 1)
        ratio = float(width_part) / float(height_part)
        if not math.isfinite(ratio) or ratio <= 0:
            raise ValueError
    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
        ratio = 16 / 9
    base = 1080 if "1080" in str(resolution).casefold() else 720
    if ratio >= 1:
        height = base
        width = round(height * ratio)
    else:
        width = base
        height = round(width / ratio)
    return (max(2, width // 2 * 2), max(2, height // 2 * 2))


def _ffconcat_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "'\\''")


def _require_real_directory(path: Path) -> None:
    try:
        path_stat = path.lstat()
    except FileNotFoundError as exc:
        raise StorageIntegrityError(
            f"Runtime task-work 父目录不存在: {path}",
        ) from exc
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode):
        raise StorageIntegrityError(f"Runtime task-work 路径不安全: {path}")


def _ensure_real_directory_chain(root: Path, *segments: str) -> Path:
    """Create one descendant chain without ever following a symlink parent."""

    _require_real_directory(root)
    current = root
    for segment in segments:
        if (
            not segment
            or segment in {".", ".."}
            or "/" in segment
            or "\\" in segment
        ):
            raise StorageIntegrityError(
                f"Runtime task-work 路径段不安全: {segment!r}",
            )
        child = current / segment
        try:
            child.mkdir(mode=0o700)
        except FileExistsError:
            pass
        _require_real_directory(child)
        current = child
    return current


def _indexed_version(
    project: Project,
    version_id: str,
    *,
    require_artifact: bool,
) -> tuple[IndexedFile | None, Any]:
    version = (
        project.assets.artifact_versions_by_id.get(version_id)
        if require_artifact
        else project.assets.source_versions_by_id.get(version_id)
    )
    if version is None:
        label = "ArtifactVersion" if require_artifact else "AssetVersion"
        raise NotFoundError(f"{label} 不存在: {version_id}")
    indexed = (
        project.assets.files_by_id.get(version.file_id)
        if version.file_id is not None
        else None
    )
    if indexed is None and not (
        not require_artifact and public_source_url(version) is not None
    ):
        raise StorageIntegrityError(f"版本缺少 IndexedFile: {version_id}")
    media_type = (
        indexed.media_type if indexed is not None else version.media_type
    )
    normalized_media_type = media_type.casefold()
    if not normalized_media_type.startswith(
        ("video/", "image/"),
    ):
        raise ValidationError(f"媒体输入不是视频或图片: {version_id}")
    if (
        normalized_media_type.startswith("image/")
        and require_artifact is False
    ):
        # Source images stay outside the composition main track; only
        # generated artifact stills may back a segment (pure
        # motion-graphics cuts render generated backdrops).
        raise ValidationError(f"媒体输入不是视频: {version_id}")
    return indexed, version


def _read_set_item(
    kind: str,
    version_id: str,
    indexed: IndexedFile | None,
    checksum: str,
) -> dict[str, Any]:
    return {
        "ref": f"{kind}:{version_id}",
        "versionId": version_id,
        "fileId": indexed.file_id if indexed is not None else None,
        "checksum": checksum,
    }


def _resolved_element_input(
    project: Project,
    element: TimelineElement,
) -> tuple[IndexedFile | None, Any, str]:
    render_source = element.render_source
    if isinstance(render_source, ElementOutputRenderSource):
        selected = selected_element_output(
            project,
            find_timeline_element(project, render_source.element_id)[1],
            render_source.output_name,
        )
        if selected is None:
            raise ConflictError(
                f"Element {element.element_id} 的 render_source 尚无选中版本",
            )
        version_id = selected[1]
        indexed, version = _indexed_version(
            project,
            version_id,
            require_artifact=True,
        )
        return indexed, version, "artifact-version"
    if isinstance(render_source, ArtifactVersionRenderSource):
        indexed, version = _indexed_version(
            project,
            render_source.version_id,
            require_artifact=True,
        )
        return indexed, version, "artifact-version"
    if isinstance(render_source, SourceVersionRenderSource):
        indexed, version = _indexed_version(
            project,
            render_source.version_id,
            require_artifact=False,
        )
        return indexed, version, "asset-version"
    raise ConflictError(f"Element {element.element_id} 尚无可渲染来源")


def _motion_document_matches_text(html: str, text: str) -> bool:
    """Check whether a motion document still carries the current copy.

    The bubble's visible text is burnt into the generated motion HTML; when
    the copy is edited afterwards (review keep, manual edit) the HTML is not
    resynchronised, and rendering it as-is would burn stale copy into the
    final video. Compare after stripping tags and whitespace so line breaks
    and segmentation added at design time are tolerated.
    """

    needle = re.sub(r"\s+", "", text)
    if not needle:
        return True
    plain = re.sub(r"<[^>]+>", "", html)
    return needle in re.sub(r"\s+", "", plain)


def _motion_document_payload(
    project: Project,
    motion: Any,
) -> dict[str, Any]:
    """Render-facing facts of one MotionGraphic without loading files.

    ``checksum`` always identifies the document content (inline hash or
    the IndexedFile digest), so fingerprints never embed the raw html.
    ``html_js`` entries additionally carry the engine salt: any vendored
    runtime or prelude upgrade invalidates the render fingerprint.
    """

    if motion.html is not None:
        checksum = hashlib.sha256(motion.html.encode("utf-8")).hexdigest()
    else:
        indexed = project.assets.files_by_id.get(motion.html_file_id or "")
        if indexed is None:
            raise StorageIntegrityError(
                f"motion 文档引用的 IndexedFile 不存在: {motion.html_file_id}",
            )
        checksum = indexed.sha256
    payload: dict[str, Any] = {
        "format": motion.format,
        "html": motion.html,
        "html_file_id": motion.html_file_id,
        "checksum": checksum,
    }
    if motion.format == "html_js":
        payload["engine"] = full_engine_digest()
    return payload


def _edit_overlays(
    project: Project,
    timeline: Timeline,
    element: TimelineElement,
) -> tuple[Mapping[str, Any], ...]:
    """Project all matching text Overlays onto one edit input.

    Overlays are returned in z_index order so the caller can burn them
    sequentially and have them stack correctly.
    """

    def _owned(candidate: TimelineElement) -> bool:
        # Transition design requires adjacent Edit spans to overlap slightly;
        # an Overlay aligned with one Edit grazes the neighbour inside that
        # overlap. Attribute by majority coverage so grazing does not count,
        # otherwise every transition boundary would be rejected as stacked
        # Overlays and composition would fail.
        start = max(element.span.start_tick, candidate.span.start_tick)
        end = min(element.span.end_tick, candidate.span.end_tick)
        overlap = max(0, end - start)
        return overlap * 2 > candidate.span.duration_tick

    overlays = sorted(
        (
            candidate
            for candidate in timeline.elements_by_id.values()
            if candidate.enabled
            and isinstance(candidate.creation, OverlayCreation)
            and candidate.creation.text.strip()
            and candidate.span.overlaps(element.span)
            and _owned(candidate)
        ),
        key=lambda candidate: (candidate.z_index, candidate.element_id),
    )
    result: list[Mapping[str, Any]] = []
    for overlay in overlays:
        intersection_start = max(
            element.span.start_tick,
            overlay.span.start_tick,
        )
        intersection_end = min(element.span.end_tick, overlay.span.end_tick)
        motion = overlay.creation.motion
        result.append(
            {
                # Fixed fallback styling tag: overlay roles derive from
                # data (non-empty text = caption).  vibe="summary" is the
                # migrated interview_summary presentation and keeps the
                # interview card fallback instead of the pet-OS bubble.
                "kind": (
                    "interview_summary"
                    if overlay.creation.vibe == "summary"
                    else "pet_os"
                ),
                "text": overlay.creation.text,
                "vibe": overlay.creation.vibe,
                "location": (
                    overlay.location.model_dump(mode="json")
                    if overlay.location is not None
                    else None
                ),
                "motion": (
                    {
                        **_motion_document_payload(project, motion),
                        "fps": motion.fps,
                        "loop": motion.loop,
                    }
                    if motion is not None
                    else None
                ),
                "appear_at": (intersection_start - element.span.start_tick)
                / timeline.ticks_per_second,
                "duration": (intersection_end - intersection_start)
                / timeline.ticks_per_second,
                "element_id": overlay.element_id,
            },
        )
    return tuple(result)


def _plan_timeline_transitions(
    timeline: Timeline,
    visual_elements: Sequence[TimelineElement],
) -> tuple[dict[str, Any], ...]:
    """Project transition Elements onto adjacent main-track segment pairs.

    Each transition must connect two adjacent visible Elements on the main
    track. The model layer already guarantees the two spans overlap and the
    transition span sits inside the intersection; here the overlap is split
    into blend (xfade duration) and tail trim (the part of the `from`
    segment directly covered by the `to` segment). Their sum equals the
    overlap exactly, so the final duration lands back on the Timeline end.
    """

    order_by_id = {
        element.element_id: index
        for index, element in enumerate(visual_elements)
    }
    ticks_per_second = timeline.ticks_per_second
    plans: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for element in sorted(
        (
            item
            for item in timeline.elements_by_id.values()
            if item.enabled and isinstance(item.creation, TransitionCreation)
        ),
        key=lambda item: (item.span.start_tick, item.element_id),
    ):
        creation = element.creation
        assert isinstance(creation, TransitionCreation)
        from_index = order_by_id.get(creation.from_element_id)
        to_index = order_by_id.get(creation.to_element_id)
        if from_index is None or to_index is None:
            raise ValidationError(
                f"转场 {element.element_id} 引用的端点不在可执行主轨中："
                f"{creation.from_element_id} -> {creation.to_element_id}",
            )
        if to_index != from_index + 1:
            raise ValidationError(
                f"转场 {element.element_id} 只能连接主轨上相邻的两个 Element；"
                f"{creation.from_element_id} 与 {creation.to_element_id} "
                "在播放顺序中不相邻。",
            )
        pair = (creation.from_element_id, creation.to_element_id)
        if pair in seen_pairs:
            raise ValidationError(
                f"同一对 Element 只支持一个转场：{pair[0]} -> {pair[1]}",
            )
        seen_pairs.add(pair)
        from_element = visual_elements[from_index]
        to_element = visual_elements[to_index]
        overlap_tick = (
            min(from_element.span.end_tick, to_element.span.end_tick)
            - to_element.span.start_tick
        )
        kind = normalize_transition_kind(creation.transition_kind)
        # The blend must not swallow either segment, or the xfade offset
        # would go backwards.
        blend_tick = (
            0
            if kind == "cut"
            else max(
                0,
                min(
                    element.span.duration_tick,
                    overlap_tick,
                    from_element.span.duration_tick - 1,
                    to_element.span.duration_tick - 1,
                ),
            )
        )
        plans.append(
            {
                "elementId": element.element_id,
                "fromElementId": creation.from_element_id,
                "toElementId": creation.to_element_id,
                "kind": kind,
                "duration_ms": round(blend_tick * 1000 / ticks_per_second),
                "tail_trim_ms": round(
                    (overlap_tick - blend_tick) * 1000 / ticks_per_second,
                ),
            },
        )
    return tuple(plans)


def _validate_contiguous_edit_elements(
    elements: Sequence[TimelineElement],
    transitions: Sequence[Mapping[str, Any]] = (),
) -> None:
    """Match Timeline edit positions to the concat-based local runner.

    The runner emits selected source ranges back-to-back; it does not render
    leading or interstitial blank media. Reject a Timeline that claims gaps or
    overlaps instead of publishing an artifact whose duration disagrees with
    the Timeline and preview playhead.  When adjacent pairs are joined by a
    transition Element, the model-mandated overlap between them is a legal
    layout.
    """

    transitioned_pairs = {
        (str(item.get("fromElementId")), str(item.get("toElementId")))
        for item in transitions
    }
    expected_start_tick = 0
    previous_id: str | None = None
    for element in elements:
        overlapped = (
            previous_id is not None
            and (previous_id, element.element_id) in transitioned_pairs
            and element.span.start_tick < expected_start_tick
        )
        if element.span.start_tick != expected_start_tick and not overlapped:
            raise ValidationError(
                "Edit Timeline 必须从 0 开始并连续排列（转场对允许重叠）；"
                f"{element.element_id} 的 span.start_tick="
                f"{element.span.start_tick}，期望 {expected_start_tick}。"
                "span 表示片段在成片中的位置；源素材时间只写在 "
                "render_source.source_in_tick/source_out_tick。",
            )
        expected_start_tick = element.span.end_tick
        previous_id = element.element_id


def _edit_motion_overlays(
    project: Project,
    timeline: Timeline,
    element: TimelineElement,
) -> tuple[Mapping[str, Any], ...]:
    """Project every generated motion Overlay onto one edit input.

    Unlike the single burned-in text overlay, any number of motion documents
    may stack on one segment; they composite in ``z_index`` order.
    """

    overlays = sorted(
        (
            candidate
            for candidate in timeline.elements_by_id.values()
            if candidate.enabled
            and isinstance(candidate.creation, OverlayCreation)
            and not candidate.creation.text.strip()
            and candidate.creation.motion is not None
            and candidate.span.overlaps(element.span)
        ),
        key=lambda candidate: (candidate.z_index, candidate.element_id),
    )
    motions: list[Mapping[str, Any]] = []
    for overlay in overlays:
        motion = overlay.creation.motion
        intersection_start = max(
            element.span.start_tick,
            overlay.span.start_tick,
        )
        intersection_end = min(element.span.end_tick, overlay.span.end_tick)
        motions.append(
            {
                "element_id": overlay.element_id,
                **_motion_document_payload(project, motion),
                "fps": motion.fps,
                "loop": motion.loop,
                "location": (
                    overlay.location.model_dump(mode="json")
                    if overlay.location is not None
                    else None
                ),
                "appear_at": (intersection_start - element.span.start_tick)
                / timeline.ticks_per_second,
                "duration": (intersection_end - intersection_start)
                / timeline.ticks_per_second,
            },
        )
    return tuple(motions)


def _append_motion_clip_input(
    *,
    project: Project,
    timeline: Timeline,
    element: TimelineElement,
    order: int,
    inputs: list[_FrozenInput],
    read_set: list[dict[str, Any]],
    selections: list[dict[str, Any]],
    durations: list[float | None],
) -> None:
    """Resolve one full-canvas motion clip element into a frozen input.

    The document is the segment's whole picture, so it must already be
    designed and externalized (content-addressed) before composition;
    an undesigned clip dead-ends the command instead of shipping a
    silent black segment.
    """

    creation = element.creation
    assert isinstance(creation, MotionClipCreation)
    motion = creation.motion
    if motion is None:
        raise ConflictError(
            f"动效片段 {element.element_id} 尚未完成动效设计，请先运行动效设计管线",
        )
    if motion.html_file_id is None:
        raise ConflictError(
            f"动效片段 {element.element_id} 的文档未外部化，请通过动效设计管线重新生成",
        )
    indexed = project.assets.files_by_id.get(motion.html_file_id)
    if indexed is None:
        raise StorageIntegrityError(
            f"动效片段引用的 IndexedFile 不存在: {motion.html_file_id}",
        )
    span_seconds = element.span.duration_tick / timeline.ticks_per_second
    payload = {
        "element_id": element.element_id,
        **_motion_document_payload(project, motion),
        "fps": motion.fps,
        "loop": motion.loop,
        "location": None,
        "appear_at": 0.0,
        "duration": span_seconds,
    }
    inputs.append(
        _FrozenInput(
            version_id=f"motion-clip-{element.element_id}",
            indexed=indexed,
            checksum=f"sha256:{indexed.sha256}",
            source_ref=f"element:{element.element_id}",
            media_type="text/html",
            start_seconds=0.0,
            end_seconds=span_seconds,
            location=(
                element.location.model_dump(mode="json")
                if element.location is not None
                else None
            ),
            overlays=_edit_overlays(project, timeline, element),
            motions=_edit_motion_overlays(project, timeline, element),
            motion_clip=payload,
        ),
    )
    read_set.append(
        _read_set_item(
            "motion-document",
            motion.html_file_id,
            indexed,
            f"sha256:{indexed.sha256}",
        ),
    )
    selections.append(
        {
            "sourceRef": f"element:{element.element_id}",
            "versionId": f"motion-clip-{element.element_id}",
            "order": order,
            "startTick": element.span.start_tick,
            "durationTick": element.span.duration_tick,
            "sourceInTick": None,
            "sourceOutTick": None,
        },
    )
    durations.append(span_seconds)


def _timeline_execution(
    *,
    project: Project,
    timeline: Timeline,
    target_ref: str,
    command: CreatorCommandType,
) -> _ResolvedExecution:
    creation_types: tuple[type, ...] = (
        (EditCreation,)
        if command is CreatorCommandType.EXECUTE_EDIT
        else (
            R2VCreation,
            T2VCreation,
            I2VCreation,
            S2VCreation,
            EditCreation,
            MotionClipCreation,
        )
    )
    visual_elements = sorted(
        (
            element
            for element in timeline.elements_by_id.values()
            if element.enabled and isinstance(element.creation, creation_types)
        ),
        key=lambda element: (element.span.start_tick, element.element_id),
    )
    if not visual_elements:
        label = (
            "Edit"
            if command is CreatorCommandType.EXECUTE_EDIT
            else "R2V/Edit"
        )
        raise ConflictError(f"Timeline 没有可执行的 {label} Element")
    transitions = _plan_timeline_transitions(timeline, visual_elements)
    if command is CreatorCommandType.EXECUTE_EDIT:
        _validate_contiguous_edit_elements(visual_elements, transitions)
    inputs: list[_FrozenInput] = []
    read_set: list[dict[str, Any]] = []
    selections: list[dict[str, Any]] = []
    durations: list[float | None] = []
    for order, element in enumerate(visual_elements, 1):
        if isinstance(element.creation, MotionClipCreation):
            _append_motion_clip_input(
                project=project,
                timeline=timeline,
                element=element,
                order=order,
                inputs=inputs,
                read_set=read_set,
                selections=selections,
                durations=durations,
            )
            continue
        indexed, version, version_kind = _resolved_element_input(
            project,
            element,
        )
        render_source = element.render_source
        start_seconds: float | None = None
        end_seconds: float | None = None
        if isinstance(element.creation, EditCreation):
            assert isinstance(render_source, SourceVersionRenderSource)
            assert not isinstance(render_source, ArtifactVersionRenderSource)
            assert render_source.source_out_tick is not None
            start_seconds = (
                render_source.source_in_tick / timeline.ticks_per_second
            )
            end_seconds = (
                render_source.source_out_tick / timeline.ticks_per_second
            )
        elif isinstance(
            element.creation,
            (R2VCreation, T2VCreation, I2VCreation, S2VCreation),
        ):
            # For generated-video elements, use the span duration to allow
            # length adjustment
            start_seconds = 0.0
            end_seconds = (
                element.span.duration_tick / timeline.ticks_per_second
            )
        inputs.append(
            _FrozenInput(
                version_id=version.version_id,
                indexed=indexed,
                checksum=version.checksum,
                source_ref=f"element:{element.element_id}",
                media_type=(
                    indexed.media_type
                    if indexed is not None
                    else version.media_type
                ),
                source_url=(
                    public_source_url(version)
                    if indexed is None and version_kind == "asset-version"
                    else None
                ),
                duration_seconds=version.duration_seconds,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                original_sound=(
                    element.creation.original_sound
                    if isinstance(element.creation, EditCreation)
                    else "preserve"
                ),
                location=(
                    element.location.model_dump(mode="json")
                    if element.location is not None
                    else None
                ),
                overlays=_edit_overlays(project, timeline, element),
                motions=_edit_motion_overlays(project, timeline, element),
            ),
        )
        read_set.append(
            _read_set_item(
                version_kind,
                version.version_id,
                indexed,
                version.checksum,
            ),
        )
        selections.append(
            {
                "sourceRef": f"element:{element.element_id}",
                "versionId": version.version_id,
                "order": order,
                "startTick": element.span.start_tick,
                "durationTick": element.span.duration_tick,
                "sourceInTick": (
                    render_source.source_in_tick
                    if isinstance(element.creation, EditCreation)
                    else None
                ),
                "sourceOutTick": (
                    render_source.source_out_tick
                    if isinstance(element.creation, EditCreation)
                    else None
                ),
            },
        )
        durations.append(
            element.span.duration_tick / timeline.ticks_per_second,
        )
    # Transitions consume the overlap of both Elements on the chain
    # (blend + tail trim), so the final duration lands back on the Timeline
    # end and stays consistent with the preview playhead.
    consumed_seconds = sum(
        (item["duration_ms"] + item["tail_trim_ms"]) / 1000
        for item in transitions
    )
    duration = (
        max(
            0.0,
            sum(item for item in durations if item is not None)
            - consumed_seconds,
        )
        if all(item is not None for item in durations)
        else None
    )
    audio_tracks: list[_FrozenAudioTrack] = []
    for element in sorted(
        (
            item
            for item in timeline.elements_by_id.values()
            if item.enabled and isinstance(item.creation, AudioCreation)
        ),
        key=lambda item: (item.span.start_tick, item.element_id),
    ):
        creation = element.creation
        assert isinstance(creation, AudioCreation)
        version = project.assets.source_versions_by_id[
            creation.source_asset_version_id
        ]
        indexed = (
            project.assets.files_by_id.get(version.file_id)
            if version.file_id is not None
            else None
        )
        audio_tracks.append(
            _FrozenAudioTrack(
                element_id=element.element_id,
                version_id=version.version_id,
                indexed=indexed,
                checksum=version.checksum,
                media_type=(
                    indexed.media_type
                    if indexed is not None
                    else version.media_type
                ),
                source_url=(
                    public_source_url(version) if indexed is None else None
                ),
                offset_seconds=(
                    element.span.start_tick / timeline.ticks_per_second
                ),
                max_duration_seconds=(
                    element.span.duration_tick / timeline.ticks_per_second
                ),
                gain_db=creation.gain_db,
                pan=creation.pan,
            ),
        )
        read_set.append(
            _read_set_item(
                "asset-version",
                version.version_id,
                indexed,
                version.checksum,
            ),
        )
    return _ResolvedExecution(
        command=command,
        target_ref=target_ref,
        task_kind=(
            TaskKind.AI_EDIT_EXECUTE
            if command is CreatorCommandType.EXECUTE_EDIT
            else TaskKind.COMPOSE
        ),
        inputs=tuple(inputs),
        transitions=transitions,
        audio_plan="",
        expected_duration_seconds=duration,
        canvas_size=_canvas_size(
            project.settings.aspect_ratio,
            project.settings.resolution,
        ),
        slot_id=f"timeline:{timeline.timeline_id}:render",
        slot_kind="final_video",
        owner_ref=f"timeline:{timeline.timeline_id}",
        artifact_name=(
            f"{project.name} AI 剪辑成片"
            if command is CreatorCommandType.EXECUTE_EDIT
            else f"{project.name} 最终成片"
        ),
        read_set=tuple(read_set),
        source_selections=tuple(selections),
        audio_tracks=tuple(audio_tracks),
        color_grade=timeline.color_grade,
    )


def _resolve_execution(
    *,
    snapshot: ProjectSnapshot,
    command: CreatorCommandType,
    target_ref: str,
    arguments: Mapping[str, Any],
) -> _ResolvedExecution:
    project = snapshot.project
    if command is CreatorCommandType.EXECUTE_EDIT:
        timeline = _target_timeline(project, target_ref)
        return _timeline_execution(
            project=project,
            timeline=timeline,
            target_ref=target_ref,
            command=command,
        )
    if command is CreatorCommandType.COMPOSE_FINAL_VIDEO:
        timeline = _target_timeline(project, target_ref)
        # Scene-loop gate (upstream scene_gate): a declared ledger must be
        # fully locked with fresh fingerprints before the expensive master
        # render; the check itself is pure computation.
        from services.render_review.scene_review import (
            validate_scene_ledger_locked,
        )

        validate_scene_ledger_locked(timeline)
        return _timeline_execution(
            project=project,
            timeline=timeline,
            target_ref=target_ref,
            command=command,
        )
    raise ValidationError(f"不支持的本地媒体命令: {command.value}")


def _fingerprint_motion(motion: Mapping[str, Any]) -> dict[str, Any]:
    """Project one motion mapping for fingerprinting.

    The raw html body never enters the fingerprint; ``checksum`` (plus the
    engine salt for html_js) fully identifies the rendered output, and it
    is available without loading externalized documents from disk.
    """

    return {key: value for key, value in motion.items() if key != "html"}


def _fingerprint_overlay(
    overlay: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if overlay is None:
        return None
    data = dict(overlay)
    motion = data.get("motion")
    if isinstance(motion, Mapping):
        data["motion"] = _fingerprint_motion(motion)
    return data


def _resolved_fingerprint(resolved: _ResolvedExecution) -> str:
    """Fingerprint of render content: covers only inputs that affect output.

    Deliberately excludes the Project's generation/etag — unrelated commits
    (Agent sessions, source analysis, ...) must not change the fingerprint,
    otherwise an identical final video would be treated as new content and
    recomposed over and over.
    """

    return _fingerprint(
        {
            "command": resolved.command.value,
            # Renderer behaviour version: bump it when a semantic fix in the
            # rendering logic (e.g. the stale motion-document fallback) must
            # invalidate old renders and force recomposition.
            # v3: audio is filter-concatenated from decoded segments — the
            # stream-copied joints produced oversized AAC packets browsers
            # refuse to decode, freezing every seek past the first joint.
            # v4: html_js overlays no longer receive the legacy
            # viewport-safety CSS injection whose wildcard font overrides
            # stomped the blueprint clamps in the composite only.
            "rendererVersion": 4,
            "targetRef": resolved.target_ref,
            "inputs": [
                {
                    "versionId": item.version_id,
                    "fileId": (
                        item.indexed.file_id
                        if item.indexed is not None
                        else None
                    ),
                    "checksum": item.checksum,
                    "sourceUrl": item.source_url,
                    "sourceRef": item.source_ref,
                    "start": item.start_seconds,
                    "end": item.end_seconds,
                    "originalSound": item.original_sound,
                    "location": item.location,
                    "overlays": [
                        _fingerprint_overlay(o) for o in item.overlays
                    ],
                    "motions": [
                        _fingerprint_motion(motion) for motion in item.motions
                    ],
                    # Key omitted for media-backed inputs so every
                    # fingerprint computed before motion clips existed
                    # stays byte-identical (no mass recomposition).
                    **(
                        {
                            "motionClip": _fingerprint_motion(
                                item.motion_clip,
                            ),
                        }
                        if item.motion_clip is not None
                        else {}
                    ),
                }
                for item in resolved.inputs
            ],
            "transitions": list(resolved.transitions),
            "audioPlan": resolved.audio_plan,
            "canvasSize": list(resolved.canvas_size),
            # Only present when a grade is configured so every historical
            # fingerprint (and its reusable render) stays byte-identical.
            **(
                {"colorGrade": resolved.color_grade}
                if resolved.color_grade
                else {}
            ),
            # Only present when the Timeline has audio Elements so historical
            # audio-free fingerprints (and their reusable renders) survive.
            **(
                {
                    "audioTracks": [
                        {
                            "versionId": track.version_id,
                            "checksum": track.checksum,
                            "offset": track.offset_seconds,
                            "maxDuration": track.max_duration_seconds,
                            "gainDb": track.gain_db,
                            "pan": track.pan,
                        }
                        for track in resolved.audio_tracks
                    ],
                }
                if resolved.audio_tracks
                else {}
            ),
        },
    )


def _fresh_slot_version(
    project: Project,
    slot_id: str,
) -> ArtifactVersion | None:
    """Return the slot's currently selected fresh version, or None."""

    slot = project.assets.artifact_slots_by_id.get(slot_id)
    if slot is None or not slot.selected_version_id:
        return None
    version = project.assets.artifact_versions_by_id.get(
        slot.selected_version_id,
    )
    if version is None or version.stale:
        return None
    return version


def _reusable_succeeded_task(
    executions: ProjectExecutionStore,
    project: Project,
    *,
    slot_id: str,
    fingerprint: str,
) -> TaskRecord | None:
    """Return the succeeded Task whose fingerprint matches the selected fresh
    artifact, avoiding a duplicate composition."""

    version = _fresh_slot_version(project, slot_id)
    if version is None or version.input_fingerprint != fingerprint:
        return None
    task_id = version.metadata.get("taskId")
    if not isinstance(task_id, str) or not task_id:
        return None
    try:
        task = executions.get_task(project.project_id, task_id)
    except RecordNotFoundError:
        return None
    if task.status is not TaskStatus.SUCCEEDED:
        return None
    if not isinstance(task.result, dict):
        return None
    return task


def _json_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _terminal_task_message(task: TaskRecord) -> str:
    message = f"本地媒体 Task 已终止: {task.status.value}"
    if isinstance(task.error, Mapping):
        detail = str(task.error.get("message") or "").strip()
        if detail and detail != message:
            message = f"{message}: {detail}"
    return message


def _materialized_motion(
    project: Project,
    file_store: AssetFileStore,
    motion: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Load one externalized motion document body for rendering.

    Content is verified against the IndexedFile digest on open, so a
    corrupted or swapped file fails the task instead of rendering silently
    wrong frames.
    """

    if motion.get("html"):
        return motion
    file_id = str(motion.get("html_file_id") or "")
    indexed = project.assets.files_by_id.get(file_id)
    if indexed is None:
        raise StorageIntegrityError(
            f"motion 文档引用的 IndexedFile 不存在: {file_id}",
        )
    with file_store.open_verified(indexed) as stream:
        html = stream.read().decode("utf-8")
    return {**motion, "html": html}


def _materialized_overlay(
    project: Project,
    file_store: AssetFileStore,
    overlay: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if overlay is None:
        return None
    motion = overlay.get("motion")
    if not isinstance(motion, Mapping) or motion.get("html"):
        return overlay
    return {
        **overlay,
        "motion": _materialized_motion(project, file_store, motion),
    }


class FileLocalMediaExecutionService:
    """Convergent Run/Task worker for local edit and compose execution."""

    def __init__(
        self,
        services: CreatorFileServices,
        *,
        runner: LocalMediaRunner | None = None,
        max_output_bytes: int = _MAX_VIDEO_BYTES,
    ) -> None:
        if max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        self.services = services
        self.runner = runner or FfmpegLocalMediaRunner()
        self.executions = ProjectExecutionStore(services.root)
        self.max_output_bytes = max_output_bytes
        self._closed = False

    async def execute(
        self,
        *,
        project_id: str,
        command: CreatorCommandType | str,
        target_ref: str,
        arguments: Mapping[str, Any],
        idempotency_key: str,
        expected_object_versions: Sequence[str] = (),
    ) -> FileLocalMediaExecutionResult:
        if self._closed:
            raise ConflictError("本地媒体执行服务正在关闭")
        command_value = CreatorCommandType(command)
        if command_value not in _LOCAL_MEDIA_COMMANDS:
            raise ValidationError(f"不支持的文件本地媒体命令: {command_value.value}")
        ids = self._ids(project_id, idempotency_key)
        command_request_hash = _fingerprint(
            {
                "command": command_value.value,
                "targetRef": target_ref,
                "arguments": dict(arguments),
            },
        )
        try:
            existing_task = await asyncio.to_thread(
                self.executions.get_task,
                project_id,
                ids["task_id"],
            )
        except RecordNotFoundError:
            existing_task = None
        if existing_task is not None:
            self._assert_command_replay(
                existing_task,
                command=command_value,
                target_ref=target_ref,
                command_request_hash=command_request_hash,
            )
            if existing_task.status is TaskStatus.SUCCEEDED:
                return self._result_from_task(existing_task, replayed=True)
            if existing_task.status in {
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
                TaskStatus.QUARANTINED,
            }:
                raise ConflictError(_terminal_task_message(existing_task))
            if existing_task.status is TaskStatus.RUNNING:
                if existing_task.result is None:
                    raise ConflictError("本地媒体 Task 已由另一个执行者领取")
                return await self._converge(
                    task=existing_task,
                    ids=ids,
                    replayed=True,
                )

        base = await asyncio.to_thread(self.services.projects.read, project_id)
        if any(
            f"project:{base.etag}:" not in value
            for value in expected_object_versions
        ):
            raise ConflictError("本地媒体命令目标已被其他写者修改")
        if command_value is CreatorCommandType.COMPOSE_FINAL_VIDEO:
            from services.render_review.scene_review import (
                auto_review_stale_scenes,
                collect_scene_review_targets,
            )

            timeline = _target_timeline(base.project, target_ref)
            stale, drafts = collect_scene_review_targets(timeline)
            if stale or drafts:
                await auto_review_stale_scenes(
                    self.services,
                    project_id=project_id,
                    timeline_ref=target_ref,
                    timeline=timeline,
                )
                base = await asyncio.to_thread(
                    self.services.projects.read,
                    project_id,
                )
        resolved = await asyncio.to_thread(
            _resolve_execution,
            snapshot=base,
            command=command_value,
            target_ref=target_ref,
            arguments=dict(arguments),
        )
        reviews = await asyncio.to_thread(
            self.services.reviews.all_pending,
            project_id,
        )
        assert_media_review_admission(
            reviews=reviews,
            command_type=resolved.command.value,
            target_ref=resolved.target_ref,
            reference_version_ids=tuple(
                item.version_id for item in resolved.inputs
            ),
        )
        logger.info(
            "local_media execute: project=%s task=%s command=%s",
            project_id,
            ids["task_id"],
            command_value.value,
        )
        request_fingerprint = _resolved_fingerprint(resolved)
        reuse = await asyncio.to_thread(
            _reusable_succeeded_task,
            self.executions,
            base.project,
            slot_id=resolved.slot_id,
            fingerprint=request_fingerprint,
        )
        if reuse is not None:
            # Render content is identical to the last successful composition
            # and the artifact is still fresh: replay the existing result
            # instead of dispatching a new composition task.
            try:
                return self._result_from_task(reuse, replayed=True)
            except StorageIntegrityError:
                pass
        run, task = await self._admit(
            base=base,
            resolved=resolved,
            request_fingerprint=request_fingerprint,
            command_request_hash=command_request_hash,
            idempotency_key=idempotency_key,
            ids=ids,
        )
        if task.status is TaskStatus.SUCCEEDED:
            return self._result_from_task(task, replayed=True)
        if task.status in {
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.QUARANTINED,
        }:
            raise ConflictError(_terminal_task_message(task))
        if task.status is TaskStatus.RUNNING and task.result is not None:
            return await self._converge(task=task, ids=ids, replayed=True)

        task = await self._start(
            run=run,
            task=task,
            resolved=resolved,
            ids=ids,
        )
        if not await self._claim_runner(task):
            raise ConflictError("本地媒体 Task 已由另一个执行者领取")
        try:
            spec = await asyncio.to_thread(
                self._prepare_spec,
                base,
                resolved,
                task,
            )
            total_elements = _render_element_total(spec.inputs)
            if spec.on_element_done is not None and total_elements > 0:
                spec.on_element_done(0, total_elements)
            runner_output = await self.runner.render(spec)
            published_result = await asyncio.to_thread(
                self._materialize_and_publish,
                base,
                resolved,
                task,
                ids,
                spec,
                runner_output,
            )
            latest = await asyncio.to_thread(
                self.executions.get_task,
                project_id,
                task.task_id,
            )
            if latest.status is TaskStatus.CANCELLED:
                await self._quarantine(
                    task=latest,
                    ids=ids,
                    reason="TASK_CANCELLED_BEFORE_IMPORT",
                    result=published_result,
                    run_status=SpecialistRunStatus.CANCELLED,
                )
                raise ConflictError("本地媒体 Task 已取消，迟到结果已隔离")
            try:
                task = await asyncio.to_thread(
                    self.executions.transition_task,
                    project_id,
                    task.task_id,
                    expected_status=TaskStatus.RUNNING,
                    status=TaskStatus.RUNNING,
                    updates={
                        "progress": max(0.9, latest.progress or 0.0),
                        "result": published_result,
                        "output_refs": [
                            f"artifact-version:{ids['artifact_version_id']}",
                        ],
                    },
                )
            except ExecutionStateConflict:
                latest = await asyncio.to_thread(
                    self.executions.get_task,
                    project_id,
                    task.task_id,
                )
                if latest.status is not TaskStatus.CANCELLED:
                    raise
                await self._quarantine(
                    task=latest,
                    ids=ids,
                    reason="TASK_CANCELLED_BEFORE_IMPORT",
                    result=published_result,
                    run_status=SpecialistRunStatus.CANCELLED,
                )
                raise ConflictError("本地媒体 Task 已取消，迟到结果已隔离")
            return await self._converge(task=task, ids=ids, replayed=False)
        except (ConflictError, ValidationError, StorageIntegrityError) as exc:
            await self._fail_if_running(
                project_id,
                ids,
                "LOCAL_MEDIA_EXECUTION_FAILED",
                message=str(exc),
            )
            raise
        except AssetFileError as exc:
            await self._fail_if_running(
                project_id,
                ids,
                "LOCAL_MEDIA_EXECUTION_FAILED",
                message=str(exc),
            )
            raise StorageIntegrityError(str(exc)) from exc
        except Exception as exc:
            await self._fail_if_running(
                project_id,
                ids,
                "LOCAL_MEDIA_EXECUTION_FAILED",
                message=str(exc),
            )
            raise StorageIntegrityError(f"本地媒体执行失败: {exc}") from exc

    @staticmethod
    def _ids(project_id: str, key: str) -> dict[str, str]:
        return {
            "run_id": _stable_id("run", project_id, key),
            "round_id": _stable_id("round", project_id, key),
            "task_id": _stable_id("task", project_id, key),
            "attempt_id": _stable_id("attempt", project_id, key),
            "attempt_started_event_id": _stable_id(
                "attempt-started",
                project_id,
                key,
            ),
            "attempt_succeeded_event_id": _stable_id(
                "attempt-succeeded",
                project_id,
                key,
            ),
            "attempt_failed_event_id": _stable_id(
                "attempt-failed",
                project_id,
                key,
            ),
            "attempt_quarantined_event_id": _stable_id(
                "attempt-quarantined",
                project_id,
                key,
            ),
            "file_id": _stable_id("file", project_id, key),
            "artifact_version_id": _stable_id(
                "artifact-version",
                project_id,
                key,
            ),
            "transaction_id": _stable_id("media-transaction", project_id, key),
            "quarantine_id": _stable_id("quarantine", project_id, key),
        }

    async def _admit(
        self,
        *,
        base: ProjectSnapshot,
        resolved: _ResolvedExecution,
        request_fingerprint: str,
        command_request_hash: str,
        idempotency_key: str,
        ids: Mapping[str, str],
    ) -> tuple[SpecialistRunRecord, TaskRecord]:
        metadata = {
            "commandType": resolved.command.value,
            "targetRef": resolved.target_ref,
            "commandRequestHash": command_request_hash,
            "slotId": resolved.slot_id,
            "artifactVersionId": ids["artifact_version_id"],
            "fileId": ids["file_id"],
        }
        run_candidate = SpecialistRunRecord(
            run_id=ids["run_id"],
            project_id=base.project.project_id,
            round_id=ids["round_id"],
            role=SpecialistRole.AI_EDITING_DIRECTOR,
            target_refs=[resolved.target_ref],
            input_generation=base.generation,
            input_etag=base.etag,
            request_fingerprint=request_fingerprint,
            read_set=list(resolved.read_set),
            caused_by_request_id=idempotency_key,
            review_policy=ReviewPolicy.AUTO_FIX,
            metadata=metadata,
        )
        try:
            run = await asyncio.to_thread(
                self.executions.get_run,
                base.project.project_id,
                ids["run_id"],
            )
        except RecordNotFoundError:
            run = await asyncio.to_thread(
                self.executions.create_run,
                run_candidate,
            )
        if (
            run.request_fingerprint != request_fingerprint
            or run.input_etag != base.etag
            or run.target_refs != [resolved.target_ref]
        ):
            raise ConflictError("Idempotency-Key 已用于不同的本地媒体 Run")
        task_candidate = TaskRecord(
            task_id=ids["task_id"],
            project_id=base.project.project_id,
            round_id=ids["round_id"],
            run_id=ids["run_id"],
            kind=resolved.task_kind,
            request_fingerprint=request_fingerprint,
            idempotency_key=idempotency_key,
            input_generation=base.generation,
            input_etag=base.etag,
            expected_target_version=base.etag,
            input_refs=[
                resolved.target_ref,
                *(item.version_id for item in resolved.inputs),
            ],
            read_set=list(resolved.read_set),
            caused_by_request_id=idempotency_key,
            review_policy=ReviewPolicy.AUTO_FIX,
            metadata=metadata,
        )
        try:
            task = await asyncio.to_thread(
                self.executions.get_task,
                base.project.project_id,
                ids["task_id"],
            )
        except RecordNotFoundError:
            try:
                task = await asyncio.to_thread(
                    self.executions.create_task,
                    task_candidate,
                )
            except (ExecutionPayloadConflict, ExecutionStateConflict) as exc:
                raise ConflictError(str(exc)) from exc
        if (
            task.request_fingerprint != request_fingerprint
            or task.input_etag != base.etag
            or task.input_refs != task_candidate.input_refs
        ):
            raise ConflictError("Idempotency-Key 已用于不同的本地媒体 Task")
        return run, task

    @staticmethod
    def _assert_command_replay(
        task: TaskRecord,
        *,
        command: CreatorCommandType,
        target_ref: str,
        command_request_hash: str,
    ) -> None:
        if (
            task.metadata.get("commandType") != command.value
            or task.metadata.get("targetRef") != target_ref
            or task.metadata.get("commandRequestHash") != command_request_hash
        ):
            raise ConflictError("Idempotency-Key 已用于不同的本地媒体命令")

    async def _claim_runner(self, task: TaskRecord) -> bool:
        claim = {
            "taskId": task.task_id,
            "requestFingerprint": task.request_fingerprint,
            "claimedAt": datetime.now(UTC).isoformat(),
        }

        def claim_sync():
            with self.services.projects.lifecycle_lock(task.project_id):
                self.services.projects.read(task.project_id)
                project_root = self.services.projects.project_root(
                    task.project_id,
                )
                task_root = _ensure_real_directory_chain(
                    project_root,
                    "runtime",
                    "tasks",
                    task.task_id,
                )
                claim_store = AtomicJsonRecordStore(
                    task_root / "runner-claim.json",
                )
                created = claim_store.try_create(claim)
                existing = None if created is not None else claim_store.read()
                return created, existing

        created, existing = await asyncio.to_thread(claim_sync)
        if created is not None:
            return True
        assert isinstance(existing, dict)
        if (
            existing.get("taskId") != task.task_id
            or existing.get("requestFingerprint") != task.request_fingerprint
        ):
            raise StorageIntegrityError("本地媒体 runner claim 内容损坏")
        return False

    async def _start(
        self,
        *,
        run: SpecialistRunRecord,
        task: TaskRecord,
        resolved: _ResolvedExecution,
        ids: Mapping[str, str],
    ) -> TaskRecord:
        project_id = task.project_id
        if run.status in {
            SpecialistRunStatus.QUEUED,
            SpecialistRunStatus.QUEUED_CAPACITY,
        }:
            run = await asyncio.to_thread(
                self.executions.transition_run,
                project_id,
                run.run_id,
                expected_status=run.status,
                status=SpecialistRunStatus.RUNNING_MODEL,
            )
        if task.status is TaskStatus.QUEUED:
            await asyncio.to_thread(
                self.executions.append_attempt,
                project_id,
                task.task_id,
                event_id=ids["attempt_started_event_id"],
                attempt_id=ids["attempt_id"],
                status=TaskAttemptStatus.RUNNING,
                input={
                    "command": resolved.command.value,
                    "targetRef": resolved.target_ref,
                    "inputs": [
                        {
                            "versionId": item.version_id,
                            "fileId": (
                                item.indexed.file_id
                                if item.indexed is not None
                                else None
                            ),
                            "checksum": item.checksum,
                            "sourceUrl": item.source_url,
                            "start": item.start_seconds,
                            "end": item.end_seconds,
                        }
                        for item in resolved.inputs
                    ],
                    "artifactVersionId": ids["artifact_version_id"],
                },
            )
            task = await asyncio.to_thread(
                self.executions.get_task,
                project_id,
                task.task_id,
            )
        if run.status is SpecialistRunStatus.RUNNING_MODEL:
            await asyncio.to_thread(
                self.executions.transition_run,
                project_id,
                run.run_id,
                expected_status=SpecialistRunStatus.RUNNING_MODEL,
                status=SpecialistRunStatus.WAITING_RUNTIME,
            )
        return task

    def _prepare_spec(
        self,
        base: ProjectSnapshot,
        resolved: _ResolvedExecution,
        task: TaskRecord,
    ) -> LocalMediaExecutionSpec:
        project_root = self.services.projects.project_root(
            base.project.project_id,
        )
        work_dir = _ensure_real_directory_chain(
            project_root,
            "runtime",
            "task-work",
            task.task_id,
        )
        input_dir = _ensure_real_directory_chain(work_dir, "inputs")
        file_store = AssetFileStore(project_root)
        local_inputs: list[LocalMediaInput] = []
        prepared_paths: dict[tuple[str, str, str], Path] = {}
        runtime_tasks = (
            self.executions.list_tasks(base.project.project_id)
            if any(item.source_url is not None for item in resolved.inputs)
            else []
        )
        for frozen in resolved.inputs:
            location_identity = (
                frozen.indexed.file_id
                if frozen.indexed is not None
                else str(frozen.source_url or "")
            )
            input_identity = (
                frozen.version_id,
                frozen.checksum,
                location_identity,
            )
            destination = prepared_paths.get(input_identity)
            suffix = mimetypes.guess_extension(frozen.media_type) or ".mp4"
            if not suffix.startswith(".") or len(suffix) > 12:
                suffix = ".mp4"
            if destination is None:
                destination = input_dir / (
                    f"{len(prepared_paths):06d}-{frozen.version_id}{suffix}"
                )
                if destination.exists():
                    raise StorageIntegrityError("Task input scratch 已存在")
                if frozen.indexed is not None:
                    with (
                        file_store.open_verified(frozen.indexed) as source,
                        destination.open("xb") as target,
                    ):
                        shutil.copyfileobj(source, target, length=1024 * 1024)
                        target.flush()
                        os.fsync(target.fileno())
                elif frozen.source_url is not None:
                    source_version = (
                        base.project.assets.source_versions_by_id.get(
                            frozen.version_id,
                        )
                    )
                    cached = (
                        resolve_remote_cache(
                            project_root,
                            source_version,
                            runtime_tasks,
                        )
                        if source_version is not None
                        else None
                    )
                    if cached is not None:
                        destination = cached.path
                    else:
                        download_remote_file(
                            frozen.source_url,
                            str(destination),
                        )
                else:
                    raise StorageIntegrityError(
                        f"媒体输入缺少本地文件与公网 URL: {frozen.version_id}",
                    )
                prepared_paths[input_identity] = destination
            local_inputs.append(
                LocalMediaInput(
                    version_id=frozen.version_id,
                    file_id=(
                        frozen.indexed.file_id
                        if frozen.indexed is not None
                        else None
                    ),
                    checksum=frozen.checksum,
                    media_type=frozen.media_type,
                    path=destination,
                    source_ref=frozen.source_ref,
                    start_seconds=frozen.start_seconds,
                    end_seconds=frozen.end_seconds,
                    duration_seconds=frozen.duration_seconds,
                    original_sound=frozen.original_sound,
                    location=frozen.location,
                    overlays=tuple(
                        _materialized_overlay(
                            base.project,
                            file_store,
                            overlay,
                        )
                        for overlay in frozen.overlays
                    ),
                    motions=tuple(
                        _materialized_motion(
                            base.project,
                            file_store,
                            motion,
                        )
                        for motion in frozen.motions
                    ),
                    motion_clip=(
                        _materialized_motion(
                            base.project,
                            file_store,
                            frozen.motion_clip,
                        )
                        if frozen.motion_clip is not None
                        else None
                    ),
                ),
            )
        output_path = work_dir / "output.mp4"
        if output_path.exists():
            raise StorageIntegrityError("Task output scratch 已存在")

        audio_dir: Path | None = None
        local_audio_tracks: list[dict[str, Any]] = []
        for track_index, track in enumerate(resolved.audio_tracks):
            if audio_dir is None:
                audio_dir = _ensure_real_directory_chain(work_dir, "audio")
            suffix = mimetypes.guess_extension(track.media_type) or ".wav"
            if not suffix.startswith(".") or len(suffix) > 12:
                suffix = ".wav"
            destination = audio_dir / (
                f"{track_index:06d}-{track.version_id}{suffix}"
            )
            if destination.exists():
                raise StorageIntegrityError("Task audio scratch 已存在")
            if track.indexed is not None:
                with (
                    file_store.open_verified(track.indexed) as source,
                    destination.open("xb") as target,
                ):
                    shutil.copyfileobj(source, target, length=1024 * 1024)
                    target.flush()
                    os.fsync(target.fileno())
            elif track.source_url is not None:
                download_remote_file(track.source_url, str(destination))
            else:
                raise StorageIntegrityError(
                    f"音频输入缺少本地文件与公网 URL: {track.version_id}",
                )
            local_audio_tracks.append(
                {
                    "element_id": track.element_id,
                    "version_id": track.version_id,
                    "path": destination,
                    "offset_seconds": track.offset_seconds,
                    "max_duration_seconds": track.max_duration_seconds,
                    "gain_db": track.gain_db,
                    "pan": track.pan,
                },
            )

        def on_element_done(done: int, total: int) -> None:
            if total <= 0:
                return
            try:
                self.executions.transition_task(
                    base.project.project_id,
                    task.task_id,
                    expected_status=TaskStatus.RUNNING,
                    status=TaskStatus.RUNNING,
                    updates={
                        "progress": min(1.0, done / total),
                        "metadata": {
                            **task.metadata,
                            "completedElements": done,
                            "totalElements": total,
                        },
                    },
                )
            except ExecutionStateConflict:
                # Cancellation or another terminal transition won the Runtime
                # lock; the renderer will observe that state before import.
                return

        spec = LocalMediaExecutionSpec(
            command=resolved.command,
            target_ref=resolved.target_ref,
            task_id=task.task_id,
            work_dir=work_dir,
            output_path=output_path,
            inputs=tuple(local_inputs),
            transitions=resolved.transitions,
            audio_plan=resolved.audio_plan,
            expected_duration_seconds=resolved.expected_duration_seconds,
            canvas_size=resolved.canvas_size,
            on_element_done=on_element_done,
            audio_tracks=tuple(local_audio_tracks),
            color_grade=resolved.color_grade,
        )
        AtomicJsonRecordStore(work_dir / "spec.json").write(
            {
                "taskId": task.task_id,
                "command": resolved.command.value,
                "targetRef": resolved.target_ref,
                "inputGeneration": base.generation,
                "inputEtag": base.etag,
                "inputs": [
                    {
                        "versionId": item.version_id,
                        "fileId": item.file_id,
                        "checksum": item.checksum,
                        "path": item.path.relative_to(project_root).as_posix(),
                        "start": item.start_seconds,
                        "end": item.end_seconds,
                        "originalSound": item.original_sound,
                        "location": item.location,
                        "overlays": [dict(o) for o in item.overlays],
                        "motions": [dict(motion) for motion in item.motions],
                    }
                    for item in local_inputs
                ],
                "outputPath": output_path.relative_to(project_root).as_posix(),
                "canvasSize": list(resolved.canvas_size),
                "audioTracks": [
                    {
                        "elementId": item["element_id"],
                        "versionId": item["version_id"],
                        "path": item["path"]
                        .relative_to(project_root)
                        .as_posix(),
                        "offset": item["offset_seconds"],
                        "maxDuration": item["max_duration_seconds"],
                        "gainDb": item["gain_db"],
                        "pan": item["pan"],
                    }
                    for item in local_audio_tracks
                ],
            },
        )
        return spec

    def _materialize_and_publish(
        self,
        base: ProjectSnapshot,
        resolved: _ResolvedExecution,
        task: TaskRecord,
        ids: Mapping[str, str],
        spec: LocalMediaExecutionSpec,
        runner_output: Mapping[str, Any],
    ) -> dict[str, Any]:
        try:
            output_stat = spec.output_path.lstat()
        except FileNotFoundError as exc:
            raise ValidationError("本地媒体 runner 未生成 output.mp4") from exc
        if spec.output_path.is_symlink() or not stat.S_ISREG(
            output_stat.st_mode,
        ):
            raise StorageIntegrityError("本地媒体输出不是普通文件")
        resolved_output = spec.output_path.resolve(strict=True)
        if not resolved_output.is_relative_to(
            spec.work_dir.resolve(strict=True),
        ):
            raise StorageIntegrityError("本地媒体输出逃逸 task-work")
        if (
            output_stat.st_size <= 0
            or output_stat.st_size > self.max_output_bytes
        ):
            raise ValidationError("本地媒体输出为空或超过大小限制")
        file_store = AssetFileStore(
            self.services.projects.project_root(base.project.project_id),
        )
        with spec.output_path.open("rb") as stream:
            staged = file_store.stage_stream(
                stream,
                staging_id=task.task_id[:80],
            )
        relative_uri = PurePosixPath(
            "assets",
            "artifacts",
            f"{ids['file_id']}.mp4",
        ).as_posix()
        indexed = IndexedFile(
            file_id=ids["file_id"],
            kind="artifact_payload",
            relative_uri=relative_uri,
            sha256=staged.sha256,
            size_bytes=staged.size_bytes,
            media_type="video/mp4",
            created_at=datetime.now(UTC),
        )
        try:
            file_store.publish(
                staged,
                relative_uri,
                expected_sha256=staged.sha256,
                expected_size_bytes=staged.size_bytes,
            )
        except AssetAlreadyExists:
            file_store.abandon(staged)
            if not file_store.inspect(indexed).available:
                raise StorageIntegrityError("稳定本地媒体输出路径已存在但内容不同")
        metadata = {
            "taskId": task.task_id,
            "runId": task.run_id,
            "commandType": resolved.command.value,
            "targetRef": resolved.target_ref,
            "sourceSelections": list(resolved.source_selections),
            "runner": _json_mapping(runner_output.get("metadata")),
        }
        reported_duration = runner_output.get("duration_seconds")
        duration = (
            float(reported_duration)
            if isinstance(reported_duration, (int, float))
            and not isinstance(reported_duration, bool)
            and float(reported_duration) >= 0
            else resolved.expected_duration_seconds
        )
        artifact = ArtifactVersion(
            version_id=ids["artifact_version_id"],
            slot_id=resolved.slot_id,
            kind=resolved.slot_kind,
            owner_ref=resolved.owner_ref,
            name=resolved.artifact_name,
            file_id=indexed.file_id,
            checksum=indexed.sha256,
            based_on_generation=task.input_generation or base.generation,
            provenance_refs=[str(item["ref"]) for item in resolved.read_set],
            duration_seconds=duration,
            input_fingerprint=task.request_fingerprint,
            created_at=indexed.created_at,
            metadata=metadata,
        )
        return {
            "taskId": task.task_id,
            "runId": task.run_id,
            "transactionId": ids["transaction_id"],
            "commandType": resolved.command.value,
            "targetRef": resolved.target_ref,
            "indexedFile": indexed.model_dump(mode="json"),
            "artifactVersion": artifact.model_dump(mode="json"),
            "outputRef": f"artifact-version:{artifact.version_id}",
        }

    async def _converge(
        self,
        *,
        task: TaskRecord,
        ids: Mapping[str, str],
        replayed: bool,
    ) -> FileLocalMediaExecutionResult:
        if not isinstance(task.result, dict):
            raise StorageIntegrityError("RUNNING 本地媒体 Task 缺少可重放 result")
        result = dict(task.result)

        def commit_if_live() -> tuple[str, TaskRecord, ProjectSnapshot | None]:
            # Cancellation and Project import share this lifecycle boundary.
            # A cancel that wins the lock leaves Project untouched; once this
            # finalizer wins, Project commit and Task success become one
            # indivisible decision from every other Project-scoped writer's
            # point of view.
            with self.services.projects.lifecycle_lock(task.project_id):
                latest = self.executions.get_task(
                    task.project_id,
                    task.task_id,
                    _lifecycle_lock_held=True,
                )
                if latest.status is TaskStatus.CANCELLED:
                    return "CANCELLED", latest, None
                if latest.status in {
                    TaskStatus.FAILED,
                    TaskStatus.QUARANTINED,
                }:
                    return latest.status.value, latest, None
                current = self.services.projects.read(task.project_id)
                if self._result_is_converged(current.project, result):
                    snapshot = current
                elif (
                    current.etag != latest.input_etag
                    or current.generation != latest.input_generation
                ) and not self._content_fingerprint_matches(current, latest):
                    # Another writer committed the Project during composition;
                    # discard the result only when the render content itself
                    # (elements/transitions/canvas, ...) actually changed.
                    # Unrelated commits must not void a freshly composed video.
                    return "STALE", latest, current
                else:
                    candidate = current.project.model_dump(mode="json")
                    self._apply_result(candidate, result)
                    # Final composition is deterministic assembly (every input
                    # was reviewed individually), so it skips the review flow;
                    # other local media artifacts follow the operator's media
                    # review mode. An AUTO_FIX round cannot carry a boundary.
                    is_final_compose = (
                        result.get("commandType")
                        == CreatorCommandType.COMPOSE_FINAL_VIDEO.value
                    )
                    review_policy = (
                        ReviewPolicy.AUTO_FIX
                        if is_final_compose
                        else media_review_policy()
                    )
                    review_boundary = (
                        None
                        if review_policy is not ReviewPolicy.REQUIRE_REVIEW
                        else self.services.commits.runtime_review_boundary(
                            task.project_id,
                            run_id=str(task.run_id),
                            request_id=latest.caused_by_request_id,
                        )
                    )
                    commit = self.services.commits.commit(
                        base=current,
                        candidate=candidate,
                        origin=ChangeOrigin.RUNTIME_TASK,
                        review_policy=review_policy,
                        review_boundary=review_boundary,
                        caused_by_request_id=latest.caused_by_request_id,
                        round_id=ids["round_id"],
                        transaction_id=ids["transaction_id"],
                        advance_accepted_baseline=True,
                        _lifecycle_lock_held=True,
                    )
                    snapshot = commit.snapshot
                success = {
                    **result,
                    "projectEtag": snapshot.etag,
                    "projectGeneration": snapshot.generation,
                }
                if latest.status is TaskStatus.RUNNING:
                    self.executions.append_attempt(
                        task.project_id,
                        task.task_id,
                        event_id=ids["attempt_succeeded_event_id"],
                        attempt_id=ids["attempt_id"],
                        status=TaskAttemptStatus.SUCCEEDED,
                        output=success,
                        output_refs=[str(success["outputRef"])],
                        _lifecycle_lock_held=True,
                    )
                    latest = self.executions.get_task(
                        task.project_id,
                        task.task_id,
                        _lifecycle_lock_held=True,
                    )
                return "SUCCEEDED", latest, snapshot

        outcome, current_task, snapshot = await asyncio.to_thread(
            commit_if_live,
        )
        if outcome == "CANCELLED":
            await self._quarantine(
                task=current_task,
                ids=ids,
                reason="TASK_CANCELLED_BEFORE_IMPORT",
                result=result,
                run_status=SpecialistRunStatus.CANCELLED,
            )
            raise ConflictError("本地媒体 Task 已取消，迟到结果已隔离")
        if outcome == "STALE":
            await self._quarantine(
                task=current_task,
                ids=ids,
                reason="PROJECT_INPUT_SNAPSHOT_STALE",
                result=result,
                run_status=SpecialistRunStatus.STALE,
            )
            raise ConflictError("本地媒体执行期间 Project 已变化，结果已隔离")
        if outcome != "SUCCEEDED" or snapshot is None:
            raise ConflictError(f"本地媒体 Task 已终止: {outcome}")
        await asyncio.to_thread(self.services.poller.note_commit, snapshot)
        success = (
            current_task.result
            if isinstance(current_task.result, dict)
            else {
                **result,
                "projectEtag": snapshot.etag,
                "projectGeneration": snapshot.generation,
            }
        )
        artifact = ArtifactVersion.model_validate(success["artifactVersion"])
        await self._finish_run(
            task.project_id,
            ids["run_id"],
            SpecialistRunStatus.SUCCEEDED,
            summary=f"已生成并选择 {artifact.name}",
        )
        return self._result_from_task(current_task, replayed=replayed)

    @staticmethod
    def _content_fingerprint_matches(
        current: ProjectSnapshot,
        task: TaskRecord,
    ) -> bool:
        """Whether the fingerprint re-resolved from the current snapshot still
        matches the one captured when the task was admitted."""

        raw_command = task.metadata.get("commandType")
        raw_target = task.metadata.get("targetRef")
        if not isinstance(raw_command, str) or not isinstance(raw_target, str):
            return False
        try:
            resolved = _resolve_execution(
                snapshot=current,
                command=CreatorCommandType(raw_command),
                target_ref=raw_target,
                arguments={},
            )
        except (ConflictError, ValidationError, ValueError):
            return False
        return _resolved_fingerprint(resolved) == task.request_fingerprint

    @staticmethod
    def _result_is_converged(
        project: Project,
        result: Mapping[str, Any],
    ) -> bool:
        try:
            indexed = IndexedFile.model_validate(result["indexedFile"])
            artifact = ArtifactVersion.model_validate(
                result["artifactVersion"],
            )
            command = CreatorCommandType(str(result["commandType"]))
        except (KeyError, TypeError, ValueError):
            return False
        slot = project.assets.artifact_slots_by_id.get(artifact.slot_id)
        if (
            project.assets.files_by_id.get(indexed.file_id) != indexed
            or project.assets.artifact_versions_by_id.get(artifact.version_id)
            != artifact
            or slot is None
            or slot.selected_version_id != artifact.version_id
        ):
            return False
        return command in {
            CreatorCommandType.EXECUTE_EDIT,
            CreatorCommandType.COMPOSE_FINAL_VIDEO,
        }

    @staticmethod
    def _apply_result(
        candidate: dict[str, Any],
        result: Mapping[str, Any],
    ) -> None:
        indexed = IndexedFile.model_validate(result["indexedFile"])
        artifact = ArtifactVersion.model_validate(result["artifactVersion"])
        assets = candidate["assets"]
        indexed_json = indexed.model_dump(mode="json")
        artifact_json = artifact.model_dump(mode="json")
        existing_file = assets["files_by_id"].get(indexed.file_id)
        if existing_file is not None and existing_file != indexed_json:
            raise ConflictError("本地媒体 IndexedFile 稳定 ID 内容冲突")
        existing_version = assets["artifact_versions_by_id"].get(
            artifact.version_id,
        )
        if existing_version is not None and existing_version != artifact_json:
            raise ConflictError("本地媒体 ArtifactVersion 稳定 ID 内容冲突")
        assets["files_by_id"][indexed.file_id] = indexed_json
        assets["artifact_versions_by_id"][artifact.version_id] = artifact_json
        raw_slot = assets["artifact_slots_by_id"].get(artifact.slot_id)
        if raw_slot is None:
            raw_slot = ArtifactSlot(
                slot_id=artifact.slot_id,
                kind=artifact.kind,
                owner_ref=artifact.owner_ref,
                version_ids=[artifact.version_id],
                selected_version_id=artifact.version_id,
            ).model_dump(mode="json")
            assets["artifact_slots_by_id"][artifact.slot_id] = raw_slot
        else:
            if (
                raw_slot["kind"] != artifact.kind
                or raw_slot["owner_ref"] != artifact.owner_ref
            ):
                raise ConflictError("本地媒体 ArtifactSlot 归属冲突")
            if artifact.version_id not in raw_slot["version_ids"]:
                raw_slot["version_ids"].append(artifact.version_id)
            raw_slot["selected_version_id"] = artifact.version_id
        command = CreatorCommandType(str(result["commandType"]))
        if command not in {
            CreatorCommandType.EXECUTE_EDIT,
            CreatorCommandType.COMPOSE_FINAL_VIDEO,
        }:
            raise ConflictError("Timeline 不支持该本地媒体命令")

    async def _quarantine(
        self,
        *,
        task: TaskRecord,
        ids: Mapping[str, str],
        reason: str,
        result: Mapping[str, Any],
        run_status: SpecialistRunStatus,
    ) -> None:
        latest = await asyncio.to_thread(
            self.executions.get_task,
            task.project_id,
            task.task_id,
        )
        if latest.status is TaskStatus.RUNNING:
            try:
                await asyncio.to_thread(
                    self.executions.append_attempt,
                    task.project_id,
                    task.task_id,
                    event_id=ids["attempt_quarantined_event_id"],
                    attempt_id=ids["attempt_id"],
                    status=TaskAttemptStatus.QUARANTINED,
                    output=dict(result),
                    output_refs=[str(result.get("outputRef") or "")],
                    error={"code": reason, "message": reason},
                )
            except ExecutionStateConflict:
                pass
        await asyncio.to_thread(
            self.executions.quarantine_task_result,
            task.project_id,
            task.task_id,
            reason=reason,
            result=dict(result),
            quarantine_id=ids["quarantine_id"],
            transition_task=False,
        )
        await self._finish_run(task.project_id, ids["run_id"], run_status)

    async def _fail_if_running(
        self,
        project_id: str,
        ids: Mapping[str, str],
        code: str,
        *,
        message: str | None = None,
    ) -> None:
        try:
            task = await asyncio.to_thread(
                self.executions.get_task,
                project_id,
                ids["task_id"],
            )
        except RecordNotFoundError:
            return
        if task.status is TaskStatus.RUNNING:
            try:
                await asyncio.to_thread(
                    self.executions.append_attempt,
                    project_id,
                    task.task_id,
                    event_id=ids["attempt_failed_event_id"],
                    attempt_id=ids["attempt_id"],
                    status=TaskAttemptStatus.FAILED,
                    error={"code": code, "message": message or code},
                )
            except ExecutionStateConflict:
                pass
        await self._finish_run(
            project_id,
            ids["run_id"],
            SpecialistRunStatus.FAILED,
        )

    async def _finish_run(
        self,
        project_id: str,
        run_id: str,
        status: SpecialistRunStatus,
        *,
        summary: str | None = None,
    ) -> None:
        try:
            run = await asyncio.to_thread(
                self.executions.get_run,
                project_id,
                run_id,
            )
        except RecordNotFoundError:
            return
        if run.status in {
            SpecialistRunStatus.SUCCEEDED,
            SpecialistRunStatus.BLOCKED,
            SpecialistRunStatus.FAILED,
            SpecialistRunStatus.STALE,
            SpecialistRunStatus.CANCELLED,
        }:
            return
        try:
            await asyncio.to_thread(
                self.executions.transition_run,
                project_id,
                run_id,
                expected_status=run.status,
                status=status,
                updates={"final_summary_text": summary} if summary else None,
            )
        except ExecutionStateConflict:
            return

    async def recover_project(self, project_id: str) -> list[str]:
        """Recover local-media Tasks after process restart.

        A RUNNING Task with a durable published result converges normally (or
        quarantines if its frozen Project input is stale).  A RUNNING Task
        without a result, and any never-started QUEUED Task, is failed closed:
        restarting ffmpeg implicitly could duplicate side effects or consume a
        partial scratch output.  A new command/idempotency key is then required.
        """

        recovered: list[str] = []
        for task in await asyncio.to_thread(
            self.executions.list_tasks,
            project_id,
        ):
            command_name = str(task.metadata.get("commandType") or "")
            try:
                command = CreatorCommandType(command_name)
            except ValueError:
                continue
            if command not in _LOCAL_MEDIA_COMMANDS or task.status not in {
                TaskStatus.QUEUED,
                TaskStatus.RUNNING,
            }:
                continue
            key = str(task.idempotency_key or "")
            if not key:
                continue
            ids = self._ids(project_id, key)
            if ids["task_id"] != task.task_id:
                raise StorageIntegrityError("本地媒体 Task 稳定 ID 与 key 不一致")
            if task.status is TaskStatus.RUNNING and task.result is not None:
                try:
                    await self._converge(task=task, ids=ids, replayed=True)
                except ConflictError:
                    # Stale/cancel convergence already persisted quarantine.
                    pass
                recovered.append(task.task_id)
                continue
            error = {
                "code": "LOCAL_MEDIA_PROCESS_RESTARTED",
                "message": "进程重启前本地媒体执行未形成可收敛结果",
            }
            if task.status is TaskStatus.RUNNING:
                try:
                    await asyncio.to_thread(
                        self.executions.append_attempt,
                        project_id,
                        task.task_id,
                        event_id=ids["attempt_failed_event_id"],
                        attempt_id=ids["attempt_id"],
                        status=TaskAttemptStatus.FAILED,
                        error=error,
                    )
                except ExecutionStateConflict:
                    pass
            else:
                await asyncio.to_thread(
                    self.executions.transition_task,
                    project_id,
                    task.task_id,
                    expected_status=TaskStatus.QUEUED,
                    status=TaskStatus.FAILED,
                    updates={"error": error},
                )
            await self._finish_run(
                project_id,
                ids["run_id"],
                SpecialistRunStatus.FAILED,
            )
            recovered.append(task.task_id)
        return recovered

    async def shutdown(self) -> None:
        """Stop admitting new work; in-flight request ownership stays explicit."""

        self._closed = True

    def _result_from_task(
        self,
        task: TaskRecord,
        *,
        replayed: bool,
    ) -> FileLocalMediaExecutionResult:
        result = task.result if isinstance(task.result, dict) else {}
        try:
            artifact = ArtifactVersion.model_validate(
                result["artifactVersion"],
            )
            transaction_id = str(result["transactionId"])
            project_etag = str(result["projectEtag"])
            project_generation = int(result["projectGeneration"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageIntegrityError(
                "SUCCEEDED 本地媒体 Task 缺少可重放结果",
            ) from exc
        # Self-review hook: every successful convergence (fresh render,
        # idempotent replay, fingerprint reuse and crash recovery) flows
        # through this single point. Scheduling is advisory and idempotent:
        # the switch, the command filter and already-reviewed dedup all live
        # on the review side.
        schedule_render_review(
            self.services,
            project_id=task.project_id,
            published_result=result,
        )
        return FileLocalMediaExecutionResult(
            task_id=task.task_id,
            run_id=str(task.run_id or ""),
            transaction_id=transaction_id,
            artifact_version_id=artifact.version_id,
            project_etag=project_etag,
            project_generation=project_generation,
            replayed=replayed,
        )


async def execute_file_local_media_command(
    services: CreatorFileServices,
    *,
    project_id: str,
    command: CreatorCommandType | str,
    target_ref: str,
    arguments: Mapping[str, Any],
    idempotency_key: str,
    expected_object_versions: Sequence[str] = (),
    runner: LocalMediaRunner | None = None,
) -> FileLocalMediaExecutionResult:
    return await FileLocalMediaExecutionService(
        services,
        runner=runner,
    ).execute(
        project_id=project_id,
        command=command,
        target_ref=target_ref,
        arguments=arguments,
        idempotency_key=idempotency_key,
        expected_object_versions=expected_object_versions,
    )


def file_local_media_task_id(
    project_id: str,
    idempotency_key: str,
) -> str:
    """Return the durable Task ID before an asynchronous runner is scheduled."""

    return FileLocalMediaExecutionService._ids(  # pylint: disable=protected-access
        project_id,
        idempotency_key,
    )[
        "task_id"
    ]


def validate_local_media_execution(
    services: CreatorFileServices,
    *,
    project_id: str,
    command: CreatorCommandType | str,
    target_ref: str,
    arguments: Mapping[str, Any] | None = None,
) -> None:
    """Synchronously pre-validate the execution plan before dispatching.

    The background runner can fail before it even creates a durable Task when
    the structure does not satisfy local composition requirements; such
    failures would be silently swallowed and the frontend would wait for a
    Task that never exists. The route layer calls this precheck first so the
    same ValidationError is raised to the caller explicitly.

    Review admission is checked here for the same reason: execute() rejects
    unreviewed inputs with ReviewPendingError before it persists the Task, so
    without this precheck the route would return 202 with a taskId that never
    materializes and the frontend would silently mark the compose as failed.
    """

    snapshot = services.projects.read(project_id)
    resolved = _resolve_execution(
        snapshot=snapshot,
        command=CreatorCommandType(command),
        target_ref=target_ref,
        arguments=dict(arguments or {}),
    )
    assert_media_review_admission(
        reviews=services.reviews.all_pending(project_id),
        command_type=resolved.command.value,
        target_ref=resolved.target_ref,
        reference_version_ids=tuple(
            item.version_id for item in resolved.inputs
        ),
    )


def find_reusable_local_media_task(
    services: CreatorFileServices,
    *,
    project_id: str,
    command: CreatorCommandType | str,
    target_ref: str,
) -> TaskRecord | None:
    """Return the succeeded Task when the current render content fingerprint
    matches the selected fresh artifact.

    Lets the route layer short-circuit before dispatch: unchanged content
    reuses the last successful composition instead of re-rendering. Any
    resolution failure returns None and normal dispatch proceeds.
    """

    try:
        command_value = CreatorCommandType(command)
    except ValueError:
        return None
    snapshot = services.projects.read(project_id)
    try:
        resolved = _resolve_execution(
            snapshot=snapshot,
            command=command_value,
            target_ref=target_ref,
            arguments={},
        )
    except (ConflictError, ValidationError):
        return None
    return _reusable_succeeded_task(
        ProjectExecutionStore(services.root),
        snapshot.project,
        slot_id=resolved.slot_id,
        fingerprint=_resolved_fingerprint(resolved),
    )


async def recover_file_local_media_project(
    services: CreatorFileServices,
    project_id: str,
) -> list[str]:
    """Lifecycle hook for startup recovery of one Project's local tasks."""

    return await FileLocalMediaExecutionService(services).recover_project(
        project_id,
    )


__all__ = [
    "FileLocalMediaExecutionResult",
    "FileLocalMediaExecutionService",
    "FfmpegLocalMediaRunner",
    "LocalMediaExecutionSpec",
    "LocalMediaInput",
    "LocalMediaRunner",
    "execute_file_local_media_command",
    "file_local_media_task_id",
    "recover_file_local_media_project",
]
