# -*- coding: utf-8 -*-
"""Rough-cut draft rendering tests — real ffmpeg, zero model calls."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from services.media_files.rough_cut import (
    RoughCutClip,
    RoughCutError,
    render_rough_cut,
)

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="requires ffmpeg on PATH",
)


def _make_video(path: Path, seconds: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=blue:s=320x240:d={seconds}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _make_still(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x240:d=0.1",
            "-frames:v",
            "1",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _duration_seconds(path_bytes: bytes, workdir: Path) -> float:
    probe_target = workdir / "probe.mp4"
    probe_target.write_bytes(path_bytes)
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(probe_target),
        ],
        check=True,
        capture_output=True,
    )
    return float(completed.stdout.decode().strip())


def test_empty_clip_list_fails_closed() -> None:
    with pytest.raises(RoughCutError, match="没有可用的粗剪素材"):
        render_rough_cut([])


@requires_ffmpeg
def test_rough_cut_concats_video_and_storyboard_still(tmp_path) -> None:
    video = tmp_path / "shot.mp4"
    still = tmp_path / "storyboard.png"
    _make_video(video, seconds=1.0)
    _make_still(still)

    payload = render_rough_cut(
        [
            RoughCutClip(
                element_id="el:1",
                kind="video",
                path=video,
                duration_seconds=1.0,
            ),
            RoughCutClip(
                element_id="el:2",
                kind="still",
                path=still,
                duration_seconds=2.0,
            ),
        ],
    )

    assert payload[:8] != b""
    duration = _duration_seconds(payload, tmp_path)
    # 1s video + 2s held still, allow container rounding.
    assert 2.5 <= duration <= 3.6
