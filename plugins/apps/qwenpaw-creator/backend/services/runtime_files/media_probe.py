# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Shared ffprobe/ffmpeg metadata probing for Creator runtime services."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import subprocess

from services.runtime_files.runtime_dependencies import (
    resolve_ffmpeg,
    resolve_ffprobe,
)


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO_SIZE_RE = re.compile(r"Video:.*?\b(\d{2,6})x(\d{2,6})\b", re.IGNORECASE)
_AUDIO_RATE_RE = re.compile(r"Audio:.*?\b(\d{3,6})\s*Hz\b", re.IGNORECASE)
_AUDIO_CHANNEL_COUNT_RE = re.compile(
    r"Audio:.*?\b(\d+)\s+channels?\b",
    re.IGNORECASE,
)


class MediaProbeError(RuntimeError):
    """A media executable was available but could not probe the target."""


class MediaProbeUnavailable(MediaProbeError):
    """Neither ffprobe nor ffmpeg is available."""


@dataclass(frozen=True, slots=True)
class MediaProbe:
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    sample_rate_hz: int | None = None
    channels: int | None = None
    has_audio: bool = False
    source: str = "unknown"


def _positive_float(value: object) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _positive_int(value: object) -> int | None:
    if value in (None, "", "N/A"):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _probe_with_ffprobe(
    executable: str,
    target: str,
    timeout: float,
) -> MediaProbe:
    completed = subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            target,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-1000:]
        raise MediaProbeError(
            f"ffprobe rejected media: {detail or completed.returncode}",
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise MediaProbeError("ffprobe returned invalid JSON") from error
    streams = payload.get("streams") if isinstance(payload, dict) else None
    streams = streams if isinstance(streams, list) else []
    video = next(
        (
            item
            for item in streams
            if isinstance(item, dict) and item.get("codec_type") == "video"
        ),
        {},
    )
    audio = next(
        (
            item
            for item in streams
            if isinstance(item, dict) and item.get("codec_type") == "audio"
        ),
        {},
    )
    raw_format = payload.get("format") if isinstance(payload, dict) else None
    media_format = raw_format if isinstance(raw_format, dict) else {}
    duration = _positive_float(media_format.get("duration"))
    if duration is None:
        duration = _positive_float(
            video.get("duration") or audio.get("duration"),
        )
    return MediaProbe(
        duration_seconds=duration,
        width=_positive_int(video.get("width")),
        height=_positive_int(video.get("height")),
        sample_rate_hz=_positive_int(audio.get("sample_rate")),
        channels=_positive_int(audio.get("channels")),
        has_audio=bool(audio),
        source="ffprobe",
    )


def _duration_from_ffmpeg(stderr: str) -> float | None:
    match = _DURATION_RE.search(stderr)
    if match is None:
        return None
    hours, minutes, seconds = match.groups()
    value = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return value if value > 0 else None


def _channels_from_ffmpeg(audio_line: str) -> int | None:
    match = _AUDIO_CHANNEL_COUNT_RE.search(audio_line)
    if match:
        return _positive_int(match.group(1))
    lowered = audio_line.casefold()
    if " mono" in lowered:
        return 1
    if " stereo" in lowered:
        return 2
    match = re.search(r"\b(\d+)\.(\d+)\b", audio_line)
    if match:
        return int(match.group(1)) + int(match.group(2))
    return None


def _probe_with_ffmpeg(
    executable: str,
    target: str,
    timeout: float,
) -> MediaProbe:
    completed = subprocess.run(
        [executable, "-hide_banner", "-i", target],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    diagnostic = completed.stderr or completed.stdout or ""
    video_match = _VIDEO_SIZE_RE.search(diagnostic)
    audio_line = next(
        (line for line in diagnostic.splitlines() if "Audio:" in line),
        "",
    )
    audio_rate = _AUDIO_RATE_RE.search(audio_line)
    result = MediaProbe(
        duration_seconds=_duration_from_ffmpeg(diagnostic),
        width=_positive_int(video_match.group(1)) if video_match else None,
        height=_positive_int(video_match.group(2)) if video_match else None,
        sample_rate_hz=_positive_int(audio_rate.group(1))
        if audio_rate
        else None,
        channels=_channels_from_ffmpeg(audio_line) if audio_line else None,
        has_audio=bool(audio_line),
        source="ffmpeg",
    )
    if not any(
        (
            result.duration_seconds,
            result.width,
            result.height,
            result.sample_rate_hz,
            result.channels,
            result.has_audio,
        ),
    ):
        detail = diagnostic.strip()[-1000:]
        raise MediaProbeError(
            f"ffmpeg could not read media metadata: {detail or completed.returncode}",
        )
    return result


def probe_media(
    target: str,
    *,
    ffmpeg_path: str | None = None,
    ffprobe_path: str | None = None,
    timeout: float = 30,
) -> MediaProbe:
    """Probe with ffprobe when available and fall back to bundled ffmpeg."""

    ffmpeg = ffmpeg_path or resolve_ffmpeg()
    ffprobe = ffprobe_path or resolve_ffprobe(ffmpeg_path=ffmpeg)
    errors: list[str] = []
    if ffprobe:
        try:
            return _probe_with_ffprobe(ffprobe, target, timeout)
        except (OSError, subprocess.SubprocessError, MediaProbeError) as error:
            errors.append(str(error))
    if ffmpeg:
        try:
            return _probe_with_ffmpeg(ffmpeg, target, timeout)
        except (OSError, subprocess.SubprocessError, MediaProbeError) as error:
            errors.append(str(error))
    if not ffprobe and not ffmpeg:
        raise MediaProbeUnavailable("ffprobe and ffmpeg are unavailable")
    raise MediaProbeError(
        "; ".join(item for item in errors if item) or "media probe failed",
    )


__all__ = [
    "MediaProbe",
    "MediaProbeError",
    "MediaProbeUnavailable",
    "probe_media",
]
