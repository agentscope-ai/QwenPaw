# -*- coding: utf-8 -*-
# flake8: noqa: E501
# Vendored from Qwen-MM-Plugins (Apache-2.0), github/main commit f9d5741.
# Upstream path: src/shared/video.py
#   (parse_time, format_timestamp, get_video_info, compute_dynamic_fps,
#    extract_frames_by_seeking) plus constants from src/shared/env.py.
# Modified for QwenPaw Creator. See backend/vendor/NOTICE.md.
"""Video reading helpers for the coarse-to-fine ``read_source_video`` tool.

Creator modifications: ffmpeg/ffprobe executables are injected by the
caller (resolved through Creator's runtime-dependency layer) instead of
PATH lookup via ``shared.syscmd.find_tool``; extracted frames return raw
JPEG bytes instead of base64 strings (Creator persists them as Runtime
files); env-var driven limits are inlined as constants.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - fixed ffmpeg/ffprobe argv, no shell
from concurrent.futures import ThreadPoolExecutor

SEEK_MAX_WORKERS = 16
# Upstream env defaults, inlined (QWEN_MM_FFMPEG_TIMEOUT / DEFAULT_FPS).
FFMPEG_TIMEOUT_SECONDS = 120
DEFAULT_FPS = 2.0


def parse_time(value: float | int | str | None) -> float | None:
    """Parse a timestamp to seconds (None passes through, for optional inputs).

    Accepts a number of seconds, or a clock string 'SS', 'MM:SS', or
    'HH:MM:SS' (fractional seconds allowed) — the same form read_video
    prints, so a displayed timestamp can be pasted back.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.endswith("s"):
        # tolerate the trailing-'s' form read_video prints (<12.3s>)
        text = text[:-1].strip()
    if ":" not in text:
        return float(text)
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(f"invalid timestamp: {value!r}")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds


def format_timestamp(seconds: float, max_seconds: float) -> str:
    if max_seconds >= 3600:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}:{minutes:02d}:{secs:04.1f}"
    if max_seconds >= 60:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}:{secs:04.1f}"
    return f"{seconds:.1f}s"


def get_video_info(ffprobe: str, video_path: str) -> dict:
    result = subprocess.run(  # nosec B603
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,duration,r_frame_rate,nb_frames",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            video_path,
        ],
        capture_output=True,
        text=True,
        timeout=FFMPEG_TIMEOUT_SECONDS,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed: {result.stderr.strip() or 'unknown error'}",
        )
    probe = json.loads(result.stdout)
    stream = probe.get("streams", [{}])[0]

    width = int(stream.get("width", 0))
    height = int(stream.get("height", 0))

    duration = float(stream.get("duration", 0))
    if duration <= 0:
        duration = float(probe.get("format", {}).get("duration", 0))

    native_fps = 30.0
    r_frame_rate = stream.get("r_frame_rate", "")
    if r_frame_rate and "/" in r_frame_rate:
        num, den = r_frame_rate.split("/")
        # Guard against "0/0" and "0/1" (both seen in the wild) — a 0 fps
        # here would divide by zero downstream; keep the 30.0 fallback.
        if int(den) > 0 and int(num) > 0:
            native_fps = int(num) / int(den)

    return {
        "width": width,
        "height": height,
        "duration": duration,
        "native_fps": native_fps,
    }


def compute_dynamic_fps(
    duration: float,
    native_fps: float,
    min_frames: int,
    max_frames: int,
    default_fps: float,
) -> tuple[float, int]:
    nframes = int(duration * default_fps)
    nframes = max(min_frames, min(max_frames, nframes))

    fps = nframes / duration if duration > 0 else default_fps
    fps = min(fps, native_fps)
    return fps, nframes


def extract_frames_by_seeking(
    ffmpeg: str,
    video_path: str,
    timestamps: list[float],
    target_h: int,
    target_w: int,
    max_workers: int = SEEK_MAX_WORKERS,
) -> list[tuple[float, bytes]]:
    """Extract frames via parallel keyframe-seeking.

    Much faster for sparse sampling. Creator modification: returns raw
    JPEG bytes per timestamp instead of base64 strings.
    """

    vf = (
        f"scale={target_w}:{target_h}"
        if target_w > 0 and target_h > 0
        else None
    )

    def _extract_one(ts: float) -> tuple[float, bytes] | None:
        cmd = [
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
        ]
        if vf:
            cmd += ["-vf", vf]
        cmd += ["-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "2", "pipe:1"]
        proc = subprocess.run(  # nosec B603
            cmd,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
            check=False,
            stdin=subprocess.DEVNULL,
        )
        if proc.returncode == 0 and proc.stdout:
            return (round(ts, 1), proc.stdout)
        return None

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(_extract_one, timestamps))
    return [item for item in results if item is not None]
