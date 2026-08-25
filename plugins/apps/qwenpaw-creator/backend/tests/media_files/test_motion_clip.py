# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=redefined-outer-name
"""Motion clip elements: a full-canvas motion document as the segment
picture (pure motion-graphics cuts)."""

from __future__ import annotations

import asyncio
import importlib.util
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
_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None

_CLIP_HTML = (
    "<!DOCTYPE html><html><head><style>"
    "html,body{margin:0;width:100%;height:100%;overflow:hidden}"
    ".stage{position:fixed;inset:0;"
    "background:linear-gradient(160deg,#1c2f5e,#7a3d8f)}"
    "</style></head><body><div class='stage'></div></body></html>"
)


@pytest.mark.skipif(
    _FFMPEG is None or _FFPROBE is None,
    reason="ffmpeg is not installed",
)
@pytest.mark.skipif(
    not _PLAYWRIGHT,
    reason="playwright is not installed (motion frames render through it)",
)
def test_motion_clip_segment_renders_the_document_as_the_picture(
    tmp_path,
) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    output = tmp_path / "output.mp4"
    spec = LocalMediaExecutionSpec(
        command=CreatorCommandType.COMPOSE_FINAL_VIDEO,
        target_ref="timeline:main",
        task_id="task-clip",
        work_dir=work_dir,
        output_path=output,
        inputs=(
            LocalMediaInput(
                version_id="motion-clip-clip-1",
                file_id="file-clip",
                checksum="sha256:clip",
                media_type="text/html",
                path=tmp_path / "unused.html",
                source_ref="element:clip-1",
                start_seconds=0.0,
                end_seconds=2.0,
                motion_clip={
                    "element_id": "clip-1",
                    "format": "html_css",
                    "html": _CLIP_HTML,
                    "checksum": "clip",
                    "fps": 24,
                    "loop": True,
                    "location": None,
                    "appear_at": 0.0,
                    "duration": 2.0,
                },
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
    # The document paints its own backdrop: the frame must not be the
    # black base canvas.
    signature = subprocess.run(
        [
            _FFMPEG,
            "-v",
            "info",
            "-ss",
            "1.0",
            "-i",
            str(output),
            "-frames:v",
            "1",
            "-vf",
            "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    yavg_lines = [
        line for line in signature.stderr.splitlines() if "YAVG" in line
    ]
    assert yavg_lines, signature.stderr
    yavg = float(yavg_lines[0].rsplit("=", 1)[1])
    assert yavg > 24.0, f"frame is almost black (YAVG={yavg})"
