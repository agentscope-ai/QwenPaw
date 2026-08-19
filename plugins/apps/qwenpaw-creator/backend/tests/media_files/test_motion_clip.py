# -*- coding: utf-8 -*-
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
from services.project_files.models import (
    MotionClipCreation,
    MotionGraphic,
    TimelineElement,
    TimelineSpan,
)

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")
_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None

_CLIP_HTML = (
    "<!DOCTYPE html><html><head><style>"
    "html,body{margin:0;width:100%;height:100%;overflow:hidden}"
    ".stage{position:fixed;inset:0;"
    "background:linear-gradient(160deg,#1c2f5e,#7a3d8f)}"
    ".orb{position:absolute;left:35%;top:30%;width:30%;height:40%;"
    "border-radius:50%;background:radial-gradient(circle,#ffd27d,#ff8a5c);"
    "animation:drift 2s linear infinite}"
    "@keyframes drift{0%{transform:translateX(-12%)}"
    "50%{transform:translateX(12%)}100%{transform:translateX(-12%)}}"
    "</style></head><body><div class='stage'><div class='orb'></div></div>"
    "</body></html>"
)


def test_motion_clip_creation_requires_prompt_or_motion() -> None:
    with pytest.raises(ValueError):
        MotionClipCreation()
    creation = MotionClipCreation(prompt="海边日落的治愈时刻")
    assert creation.type == "motion_clip"
    assert creation.motion is None


def test_motion_clip_element_round_trips() -> None:
    element = TimelineElement(
        element_id="clip-1",
        span=TimelineSpan(start_tick=0, duration_tick=4000),
        creation=MotionClipCreation(
            prompt="开场标题卡",
            motion=MotionGraphic(format="html_css", html=_CLIP_HTML),
        ),
    )
    payload = element.model_dump(mode="json")
    assert payload["creation"]["type"] == "motion_clip"
    restored = TimelineElement.model_validate(payload)
    assert isinstance(restored.creation, MotionClipCreation)


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
    assert float(probe.stdout.strip()) == pytest.approx(2.0, abs=0.15)
    # The document paints its own backdrop: the frame must not be the
    # black base canvas.
    frame = tmp_path / "frame.png"
    subprocess.run(
        [
            _FFMPEG,
            "-y",
            "-v",
            "error",
            "-ss",
            "1.0",
            "-i",
            str(output),
            "-frames:v",
            "1",
            str(frame),
        ],
        check=True,
    )
    signature = subprocess.run(
        [
            _FFMPEG,
            "-v",
            "info",
            "-i",
            str(frame),
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
