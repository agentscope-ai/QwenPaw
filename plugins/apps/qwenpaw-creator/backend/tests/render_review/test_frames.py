# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Unit tests for review frame extraction and the ebur128 audio profile."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from services.render_review.frames import (
    RenderReviewError,
    _frame_timestamps,
    _segment_loudness,
    extract_review_frames,
    probe_audio_profile,
)
from services.runtime_files.media_probe import probe_media
from services.runtime_files.runtime_dependencies import resolve_ffmpeg
from vendor.mm_plugins.image_budget import (
    IMAGE_BUDGET_TOKENS,
    IMAGE_MIN_PIXELS,
    TOKEN_SIZE,
    VIDEO_BUDGET_TOKENS,
    VIDEO_MIN_PIXELS,
    budget_to_pixels,
    smart_resize,
)

pytestmark = pytest.mark.unit

_FFMPEG = resolve_ffmpeg()
requires_ffmpeg = pytest.mark.skipif(
    _FFMPEG is None,
    reason="ffmpeg is not available",
)


def _make_video(
    path: Path,
    *,
    duration: float = 2.0,
    with_audio: bool = True,
    silent_audio: bool = False,
) -> Path:
    assert _FFMPEG is not None
    command = [
        _FFMPEG,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size=640x360:rate=24:duration={duration}",
    ]
    if with_audio:
        source = (
            f"anullsrc=r=44100:cl=stereo:d={duration}"
            if silent_audio
            else f"sine=frequency=440:duration={duration}"
        )
        command += ["-f", "lavfi", "-i", source, "-shortest"]
    command += [
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-y",
        str(path),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=120)
    return path


def test_frame_timestamps_always_include_first_and_last() -> None:
    stamps = _frame_timestamps(10.0, 24)
    assert stamps[0] == 0.0
    assert stamps[-1] == pytest.approx(9.96, abs=0.01)
    assert len(stamps) == 11
    assert stamps == sorted(stamps)

    capped = _frame_timestamps(300.0, 24)
    assert len(capped) == 24

    short = _frame_timestamps(0.5, 24)
    assert short[0] == 0.0
    assert len(short) == 2

    assert _frame_timestamps(0.0, 24) == [0.0]


@requires_ffmpeg
def test_extract_review_frames_respects_budget(tmp_path: Path) -> None:
    video = _make_video(tmp_path / "clip.mp4", duration=2.0)
    frames = extract_review_frames(
        video,
        max_frames=24,
        output_dir=tmp_path / "frames",
    )
    assert len(frames) >= 2
    assert frames[0].timestamp_ms == 0
    assert frames[-1].timestamp_ms >= 1900
    max_pixels = budget_to_pixels("normal", VIDEO_BUDGET_TOKENS)
    for frame in frames:
        path = Path(frame.image_path)
        assert path.is_file()
        assert path.stat().st_size > 0
    # The scale target is snapped to the token grid and within the budget.
    frame_probe = probe_media(frames[0].image_path)
    assert frame_probe.width is not None and frame_probe.height is not None
    assert frame_probe.width % TOKEN_SIZE == 0
    assert frame_probe.height % TOKEN_SIZE == 0
    assert frame_probe.width * frame_probe.height <= max_pixels


def test_extract_review_frames_missing_video(tmp_path: Path) -> None:
    with pytest.raises(RenderReviewError, match="video not found"):
        extract_review_frames(tmp_path / "absent.mp4")


@requires_ffmpeg
def test_probe_audio_profile_with_tone(tmp_path: Path) -> None:
    video = _make_video(tmp_path / "tone.mp4", duration=2.0)
    profile = probe_audio_profile(video)
    assert profile.has_audio is True
    assert profile.integrated_lufs is not None
    assert profile.loudness_segments
    assert any(not item.silent for item in profile.loudness_segments)


@requires_ffmpeg
def test_probe_audio_profile_without_audio_track(tmp_path: Path) -> None:
    video = _make_video(tmp_path / "mute.mp4", duration=1.0, with_audio=False)
    profile = probe_audio_profile(video)
    assert profile.has_audio is False
    assert profile.loudness_segments == []


@requires_ffmpeg
def test_probe_audio_profile_marks_silence(tmp_path: Path) -> None:
    video = _make_video(
        tmp_path / "silent.mp4",
        duration=2.0,
        silent_audio=True,
    )
    profile = probe_audio_profile(video)
    assert profile.has_audio is True
    assert profile.loudness_segments
    assert all(item.silent for item in profile.loudness_segments)


def test_segment_loudness_merges_runs() -> None:
    samples = [(index / 10, -18.0) for index in range(1, 11)]
    samples += [(1.0 + index / 10, -80.0) for index in range(1, 11)]
    segments = _segment_loudness(samples)
    assert len(segments) == 2
    assert segments[0].silent is False
    assert segments[1].silent is True
    assert segments[0].end_ms == segments[1].start_ms
    assert segments[-1].end_ms == 2000


def test_smart_resize_never_exceeds_budget() -> None:
    """Patch-grid rounding must not overshoot the pixel budget."""
    video_budget = budget_to_pixels("normal", VIDEO_BUDGET_TOKENS)
    cases = [
        (274, 913, VIDEO_MIN_PIXELS, video_budget),
        (720, 1280, VIDEO_MIN_PIXELS, video_budget),
        (1, 10_000, VIDEO_MIN_PIXELS, video_budget),
        (
            2160,
            3840,
            IMAGE_MIN_PIXELS,
            budget_to_pixels("normal", IMAGE_BUDGET_TOKENS),
        ),
    ]
    for height, width, min_pixels, max_pixels in cases:
        out_h, out_w = smart_resize(height, width, min_pixels, max_pixels)
        assert out_h % TOKEN_SIZE == 0 and out_w % TOKEN_SIZE == 0
        assert out_h * out_w <= max_pixels, (height, width, out_h, out_w)
