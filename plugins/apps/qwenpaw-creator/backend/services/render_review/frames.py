# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Frame and audio evidence extraction for the render self-review loop.

Frames are sampled uniformly across the full duration (first and last frame
always included) and resized to the VLM video resolution budget via the
vendored ``image_budget.smart_resize``. The audio profile summarizes the
ffmpeg ebur128 momentary-loudness timeline into silence/active segments for
the voiceover and engineering dimensions.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from schemas.render_review import AudioProfile, LoudnessSegment, ReviewFrame
from services.runtime_files.media_probe import probe_media
from services.runtime_files.runtime_dependencies import resolve_ffmpeg
from utils.logger import setup_logger
from vendor.media_toolkit.image_budget import (
    VIDEO_BUDGET_TOKENS,
    VIDEO_MIN_PIXELS,
    budget_to_pixels,
    smart_resize,
)

logger = setup_logger("creator.render_review.frames")

_FFMPEG_TIMEOUT_SECONDS = 120
# Momentary loudness below this is treated as silence for segmenting.
# -55 keeps quiet ambient beds (≈-50 LUFS) out of the silence class while
# still catching muted/dropped tracks (≤-70 LUFS).
_SILENCE_LUFS = -55.0
# ebur128 emits ~10 samples/second; merge runs shorter than this.
_MIN_SEGMENT_MS = 400
# The ebur128 momentary window (400ms) reads -120 LUFS until it fills up;
# drop that warm-up so clips never show a fake leading silence.
_EBUR128_WARMUP_SECONDS = 0.43

_EBUR128_LINE = re.compile(
    r"t:\s*(?P<t>[0-9.]+)\s+TARGET:\s*-?[0-9.]+ LUFS\s+M:\s*(?P<m>-?[0-9.]+|nan)",
)
_EBUR128_INTEGRATED = re.compile(r"I:\s*(-?[0-9.]+)\s*LUFS")


class RenderReviewError(RuntimeError):
    """Evidence extraction for the self-review loop failed."""


def _require_ffmpeg() -> str:
    path = resolve_ffmpeg()
    if not path:
        raise RenderReviewError("ffmpeg is not available for render review")
    return path


def _frame_timestamps(duration_seconds: float, max_frames: int) -> list[float]:
    """Uniform timestamps across the duration; first and last always sampled.

    The opening window gets extra probes: title cards and hooks live in
    the first ~3 seconds behind entrance animations, and a uniform grid
    over a long cut leaves t=0 as the only evidence there — the reviewer
    would judge the opening design by a frame taken before it entered.
    """
    if duration_seconds <= 0:
        return [0.0]
    # About one frame per second, capped by max_frames, at least two frames.
    count = max(2, min(max_frames, int(duration_seconds) + 1))
    last = max(0.0, duration_seconds - 0.04)
    if count == 2:
        return [0.0, last]
    step = last / (count - 1)
    stamps = [round(index * step, 3) for index in range(count)]
    if duration_seconds > 6 and step > 1.2:
        opening = [
            probe
            for probe in (0.8, 1.8, 2.8)
            if probe < last and all(abs(probe - s) > 0.4 for s in stamps)
        ]
        merged = sorted(set(stamps) | set(opening))
        # Respect the budget: drop mid-cut frames (never the first, the
        # opening probes or the last) until the count fits again.
        while len(merged) > max_frames:
            interior = [s for s in merged[1:-1] if s > 3.2]
            if not interior:
                break
            # Remove the interior frame whose neighbours are closest,
            # keeping coverage as even as the budget allows.
            merged.remove(interior[len(interior) // 2])
        stamps = merged
    return stamps


def _run_frame_grab(
    ffmpeg: str,
    seek_args: list[str],
    video_path: Path,
    target_width: int,
    target_height: int,
    frame_path: Path,
) -> subprocess.CompletedProcess[str]:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        *seek_args,
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        # out_range=jpeg: newer ffmpeg mjpeg encoders reject
        # limited-range YUV; -strict unofficial keeps ffmpeg 8 tolerant
        # when the decoded range stays unspecified near EOF.
        f"scale={target_width}:{target_height}:out_range=jpeg",
        "-q:v",
        "3",
        "-strict",
        "unofficial",
        "-y",
        str(frame_path),
    ]
    return subprocess.run(
        command,
        # Detach stdin so ffmpeg is not suspended by SIGTTIN when it reads
        # the tty from a background process group.
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=_FFMPEG_TIMEOUT_SECONDS,
        check=False,
    )


def extract_review_frames(
    video_path: Path,
    *,
    max_frames: int = 24,
    output_dir: Path | None = None,
) -> list[ReviewFrame]:
    """Extract evidence frames resized to the VLM video budget."""
    if not video_path.is_file():
        raise RenderReviewError(f"video not found: {video_path}")
    ffmpeg = _require_ffmpeg()
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="render-review-frames-"))
    probe = probe_media(str(video_path))
    duration = probe.duration_seconds or 0.0
    height = probe.height or 720
    width = probe.width or 1280
    target_height, target_width = smart_resize(
        height,
        width,
        VIDEO_MIN_PIXELS,
        budget_to_pixels("normal", VIDEO_BUDGET_TOKENS),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    frames: list[ReviewFrame] = []
    for index, timestamp in enumerate(_frame_timestamps(duration, max_frames)):
        timestamp_ms = int(round(timestamp * 1000))
        frame_path = output_dir / f"frame-{index:02d}-{timestamp_ms}ms.jpg"
        result = _run_frame_grab(
            ffmpeg,
            ["-ss", f"{timestamp:.3f}"],
            video_path,
            target_width,
            target_height,
            frame_path,
        )
        if result.returncode != 0 or not frame_path.is_file():
            # A fast seek can land past the final packet; grab the tail
            # frame relative to EOF instead of dropping the mandatory
            # last-frame evidence. A -0.5s window can still decode zero
            # frames when the final GOP is longer (ffmpeg exits 0 with an
            # empty output), so widen the window before giving up.
            for sseof_window in ("-0.5", "-2.0"):
                result = _run_frame_grab(
                    ffmpeg,
                    ["-sseof", sseof_window],
                    video_path,
                    target_width,
                    target_height,
                    frame_path,
                )
                if result.returncode == 0 and frame_path.is_file():
                    break
        if result.returncode != 0 or not frame_path.is_file():
            stderr = (result.stderr or "").strip()[:500]
            raise RenderReviewError(
                f"frame extraction failed at {timestamp:.3f}s: "
                + (
                    stderr
                    or (
                        f"ffmpeg exit={result.returncode} produced no "
                        "frame (empty tail GOP?)"
                    )
                ),
            )
        frames.append(
            ReviewFrame(
                timestamp_ms=timestamp_ms,
                image_path=str(frame_path),
            ),
        )
    logger.info(
        "render review frames extracted: video=%s frames=%d size=%dx%d",
        video_path.name,
        len(frames),
        target_width,
        target_height,
    )
    return frames


def _segment_loudness(
    samples: list[tuple[float, float]],
) -> list[LoudnessSegment]:
    """Merge ~100ms ebur128 momentary samples into silence/active segments."""
    segments: list[LoudnessSegment] = []
    run_start_ms: int | None = None
    run_values: list[float] = []
    run_silent = False
    previous_ms = 0

    def close_run(end_ms: int) -> None:
        if run_start_ms is None or end_ms <= run_start_ms:
            return
        mean = sum(run_values) / len(run_values) if run_values else -120.0
        segments.append(
            LoudnessSegment(
                start_ms=run_start_ms,
                end_ms=end_ms,
                mean_momentary_lufs=round(mean, 1),
                silent=run_silent,
            ),
        )

    for timestamp, momentary in samples:
        sample_ms = int(round(timestamp * 1000))
        silent = momentary < _SILENCE_LUFS
        if run_start_ms is None:
            run_start_ms = 0
            run_silent = silent
        elif silent != run_silent:
            close_run(previous_ms)
            run_start_ms = previous_ms
            run_values = []
            run_silent = silent
        run_values.append(momentary)
        previous_ms = sample_ms
    close_run(previous_ms)
    # Absorb blips shorter than the minimum segment into their neighbours.
    merged: list[LoudnessSegment] = []
    for segment in segments:
        duration_ms = segment.end_ms - segment.start_ms
        if (
            merged
            and duration_ms < _MIN_SEGMENT_MS
            and segment is not segments[-1]
        ):
            head = merged[-1]
            merged[-1] = head.model_copy(update={"end_ms": segment.end_ms})
            continue
        if merged and merged[-1].silent == segment.silent:
            head = merged[-1]
            merged[-1] = head.model_copy(update={"end_ms": segment.end_ms})
            continue
        merged.append(segment)
    return merged


def probe_audio_profile(video_path: Path) -> AudioProfile:
    """Summarize the audio track with ffmpeg ebur128 (empty when no audio)."""
    if not video_path.is_file():
        raise RenderReviewError(f"video not found: {video_path}")
    probe = probe_media(str(video_path))
    if not probe.has_audio:
        return AudioProfile(has_audio=False)
    ffmpeg = _require_ffmpeg()
    command = [
        ffmpeg,
        "-hide_banner",
        "-nostats",
        "-i",
        str(video_path),
        "-vn",
        "-af",
        "ebur128",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(
        command,
        # Detach stdin so ffmpeg is not suspended by SIGTTIN when it reads
        # the tty from a background process group.
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=_FFMPEG_TIMEOUT_SECONDS,
        check=False,
    )
    stderr = result.stderr or ""
    if result.returncode != 0:
        raise RenderReviewError(
            f"ebur128 probe failed: {stderr.strip()[:500]}",
        )
    samples: list[tuple[float, float]] = []
    for match in _EBUR128_LINE.finditer(stderr):
        timestamp = float(match.group("t"))
        if timestamp < _EBUR128_WARMUP_SECONDS:
            continue
        momentary_raw = match.group("m")
        momentary = -120.0 if momentary_raw == "nan" else float(momentary_raw)
        samples.append((timestamp, momentary))
    integrated: float | None = None
    summary_index = stderr.rfind("Summary:")
    if summary_index >= 0:
        integrated_match = _EBUR128_INTEGRATED.search(
            stderr[summary_index:],
        )
        if integrated_match is not None:
            integrated = float(integrated_match.group(1))
    return AudioProfile(
        has_audio=True,
        integrated_lufs=integrated,
        loudness_segments=_segment_loudness(samples),
    )


__all__ = [
    "RenderReviewError",
    "extract_review_frames",
    "probe_audio_profile",
]
