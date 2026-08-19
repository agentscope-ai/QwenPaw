# -*- coding: utf-8 -*-
"""Still-image segments: pure motion-graphics cuts render generated
backdrops as timeline segments (ffmpeg -loop 1 path)."""

from __future__ import annotations

import asyncio
import shutil
import subprocess

import pytest

from domain.enums import CreatorCommandType
from services.media_files.local_execution import (
    FfmpegLocalMediaRunner,
    LocalMediaExecutionSpec,
    LocalMediaInput,
)

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


@pytest.mark.skipif(
    _FFMPEG is None or _FFPROBE is None,
    reason="ffmpeg is not installed",
)
def test_still_image_input_renders_a_timed_segment(tmp_path) -> None:
    image = tmp_path / "backdrop.png"
    subprocess.run(
        [
            _FFMPEG,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=orange:s=640x360:d=0.1",
            "-frames:v",
            "1",
            str(image),
        ],
        check=True,
    )
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    output = tmp_path / "output.mp4"
    spec = LocalMediaExecutionSpec(
        command=CreatorCommandType.COMPOSE_FINAL_VIDEO,
        target_ref="timeline:main",
        task_id="task-still",
        work_dir=work_dir,
        output_path=output,
        inputs=(
            LocalMediaInput(
                version_id="artifact-version-still",
                file_id="file-still",
                checksum="sha256:still",
                media_type="image/png",
                path=image,
                source_ref="element:bg-1",
                start_seconds=0.0,
                end_seconds=2.0,
                duration_seconds=None,
            ),
        ),
        transitions=(),
        audio_plan="preserve",
        expected_duration_seconds=2.0,
        canvas_size=(640, 360),
    )
    runner = FfmpegLocalMediaRunner(_FFMPEG)
    result = asyncio.run(runner.render(spec))
    assert result["media_type"] == "video/mp4"

    assert output.exists()
    probe = subprocess.run(
        [
            _FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    duration = float(probe.stdout.strip())
    assert duration == pytest.approx(2.0, abs=0.15)
    decode = subprocess.run(
        [_FFMPEG, "-v", "error", "-i", str(output), "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert decode.returncode == 0 and not decode.stderr.strip()
