# -*- coding: utf-8 -*-
"""Shared ffmpeg-based decoding helpers for the objective fact operators.

Everything here is CPU-only and depends solely on the bundled ffmpeg
binaries plus numpy. Decoding failures raise :class:`ObjectiveIOError`;
the facts orchestrator catches it and records the operator as skipped —
objective facts are advisory hints and must never disturb a review.
"""

from __future__ import annotations

import subprocess  # nosec B404 - fixed ffmpeg/ffprobe argv, no shell
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from services.runtime_files.runtime_dependencies import (
    resolve_ffmpeg,
    resolve_ffprobe,
)
from utils.logger import setup_logger
from vendor.media_toolkit.video_read import get_video_info

logger = setup_logger("creator.run_review.objective.io")

_FFMPEG_TIMEOUT_SECONDS = 120
# Diff-curve sampling: dense enough to see cuts/freezes, cheap enough to
# run on every reviewed artifact (~8 fps at 160px width).
DIFF_SAMPLE_FPS = 8.0
DIFF_SAMPLE_WIDTH = 160
MAX_DIFF_FRAMES = 1200
# Audio analysis window: mono 16 kHz PCM capped to keep memory bounded.
PCM_SAMPLE_RATE = 16000
PCM_MAX_SECONDS = 240


class ObjectiveIOError(RuntimeError):
    """Decoding for one objective fact operator failed."""


@dataclass(frozen=True, slots=True)
class GraySamples:
    """Uniformly sampled grayscale frames of one video."""

    timestamps_ms: tuple[int, ...]
    frames: np.ndarray  # shape (n, h, w), dtype uint8

    @property
    def count(self) -> int:
        return int(self.frames.shape[0])


def _require_ffmpeg() -> str:
    path = resolve_ffmpeg()
    if not path:
        raise ObjectiveIOError("ffmpeg is not available")
    return path


def _require_ffprobe() -> str:
    path = resolve_ffprobe()
    if not path:
        raise ObjectiveIOError("ffprobe is not available")
    return path


def probe_info(video_path: Path) -> dict:
    """Container facts: width/height/duration/native_fps."""
    try:
        return get_video_info(_require_ffprobe(), str(video_path))
    except Exception as exc:  # noqa: BLE001 - normalized boundary
        raise ObjectiveIOError(f"ffprobe failed: {exc}") from exc


def _run_ffmpeg(command: list[str]) -> bytes:
    proc = subprocess.run(  # nosec B603
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=_FFMPEG_TIMEOUT_SECONDS,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()[-400:]
        raise ObjectiveIOError(f"ffmpeg failed: {detail or 'unknown error'}")
    return proc.stdout


def sample_gray_frames(
    video_path: Path,
    *,
    fps: float = DIFF_SAMPLE_FPS,
    width: int = DIFF_SAMPLE_WIDTH,
    max_frames: int = MAX_DIFF_FRAMES,
) -> GraySamples:
    """Decode a uniform low-res grayscale frame sequence in one pass."""
    info = probe_info(video_path)
    duration = float(info.get("duration") or 0.0)
    if duration <= 0:
        raise ObjectiveIOError("video reports no duration")
    effective_fps = min(fps, float(info.get("native_fps") or fps))
    expected = int(duration * effective_fps)
    if expected > max_frames:
        effective_fps = max_frames / duration
    height = max(
        2,
        int(
            round(
                width
                * int(info.get("height") or 9)
                / max(1, int(info.get("width") or 16)),
            ),
        ),
    )
    height -= height % 2
    raw = _run_ffmpeg(
        [
            _require_ffmpeg(),
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(video_path),
            "-vf",
            f"fps={effective_fps:.4f},scale={width}:{height}",
            "-pix_fmt",
            "gray",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
    )
    frame_bytes = width * height
    count = len(raw) // frame_bytes
    if count < 2:
        raise ObjectiveIOError("video decoded to fewer than 2 frames")
    frames = np.frombuffer(
        raw[: count * frame_bytes],
        dtype=np.uint8,
    ).reshape(count, height, width)
    step_ms = 1000.0 / effective_fps
    timestamps = tuple(int(round(index * step_ms)) for index in range(count))
    return GraySamples(timestamps_ms=timestamps, frames=frames)


def sample_rgb_frame(
    video_path: Path,
    *,
    timestamp_ms: int,
    width: int = 320,
) -> np.ndarray:
    """One RGB frame at ``timestamp_ms`` (shape (h, w, 3), uint8)."""
    info = probe_info(video_path)
    height = max(
        2,
        int(
            round(
                width
                * int(info.get("height") or 9)
                / max(1, int(info.get("width") or 16)),
            ),
        ),
    )
    height -= height % 2
    raw = _run_ffmpeg(
        [
            _require_ffmpeg(),
            "-nostdin",
            "-v",
            "error",
            "-ss",
            f"{timestamp_ms / 1000:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:{height}",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
    )
    expected = width * height * 3
    if len(raw) < expected:
        raise ObjectiveIOError("rgb frame decode returned no data")
    return np.frombuffer(raw[:expected], dtype=np.uint8).reshape(
        height,
        width,
        3,
    )


def decode_pcm_mono(
    media_path: Path,
    *,
    sample_rate: int = PCM_SAMPLE_RATE,
    max_seconds: int = PCM_MAX_SECONDS,
) -> np.ndarray | None:
    """Mono PCM float32 in [-1, 1]; ``None`` when there is no audio track."""
    try:
        raw = _run_ffmpeg(
            [
                _require_ffmpeg(),
                "-nostdin",
                "-v",
                "error",
                "-i",
                str(media_path),
                "-t",
                str(max_seconds),
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-f",
                "s16le",
                "pipe:1",
            ],
        )
    except ObjectiveIOError as exc:
        # A video without an audio stream is a legitimate fact, not an
        # operator failure.
        if "does not contain any stream" in str(
            exc,
        ) or "Output file does not contain" in str(exc):
            return None
        raise
    if len(raw) < 2:
        return None
    samples = np.frombuffer(raw[: len(raw) - len(raw) % 2], dtype=np.int16)
    if samples.size == 0:
        return None
    return samples.astype(np.float32) / 32768.0


__all__ = [
    "DIFF_SAMPLE_FPS",
    "GraySamples",
    "ObjectiveIOError",
    "PCM_SAMPLE_RATE",
    "decode_pcm_mono",
    "probe_info",
    "sample_gray_frames",
    "sample_rgb_frame",
]
