# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unified colour grading: one deterministic pass over the composited cut."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from domain.enums import CreatorCommandType
from services.media_files.local_execution import (
    FfmpegLocalMediaRunner,
    LocalMediaExecutionSpec,
)

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")

pytestmark = pytest.mark.skipif(
    _FFMPEG is None or _FFPROBE is None,
    reason="ffmpeg is not installed",
)


def _gray_clip(path, duration: float = 0.5) -> None:
    subprocess.run(
        [
            _FFMPEG,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=gray:s=64x64:d={duration}",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )


def _mean_rgb(path) -> tuple[float, float, float]:
    out = subprocess.run(
        [
            _FFMPEG,
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            "scale=1:1,format=rgb24",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    return float(out[0]), float(out[1]), float(out[2])


def _spec(tmp_path, output, grade: str) -> LocalMediaExecutionSpec:
    return LocalMediaExecutionSpec(
        command=CreatorCommandType.COMPOSE_FINAL_VIDEO,
        target_ref="timeline:timeline:main",
        task_id="task-grade",
        work_dir=tmp_path,
        output_path=output,
        inputs=(),
        transitions=(),
        audio_plan="",
        expected_duration_seconds=None,
        canvas_size=(64, 64),
        color_grade=grade,
    )


def test_warm_bright_grade_shifts_the_cut_towards_warm(tmp_path) -> None:
    output = tmp_path / "output.mp4"
    _gray_clip(output)
    neutral_r, _neutral_g, neutral_b = _mean_rgb(output)

    runner = FfmpegLocalMediaRunner(_FFMPEG)
    warning = runner._apply_color_grade(_spec(tmp_path, output, "warm_bright"))

    assert warning is None
    graded_r, _graded_g, graded_b = _mean_rgb(output)
    # The warm preset pushes reds up and blues down relative to neutral.
    assert graded_r - graded_b > (neutral_r - neutral_b) + 2


def test_unknown_grade_degrades_to_a_warning_and_keeps_the_cut(
    tmp_path,
) -> None:
    output = tmp_path / "output.mp4"
    _gray_clip(output)
    original = output.read_bytes()

    runner = FfmpegLocalMediaRunner(_FFMPEG)
    warning = runner._apply_color_grade(_spec(tmp_path, output, "sepia_1920"))

    assert warning is not None and "sepia_1920" in warning
    assert output.read_bytes() == original


def test_model_boundary_only_admits_the_named_preset_vocabulary() -> None:
    from services.media_files.local_execution import _COLOR_GRADE_FILTERS
    from services.project_files.models import (
        COLOR_GRADE_PRESETS,
        Project,
        Timeline,
    )

    assert set(_COLOR_GRADE_FILTERS) == set(COLOR_GRADE_PRESETS)
    project = Project.new(project_id="project-grade", name="Grade")
    base = project.timelines.items["timeline:main"].model_dump()
    with pytest.raises(ValueError, match="color_grade 必须是命名预设"):
        Timeline(**{**base, "color_grade": "明亮温暖清新"})
    # Named presets and the empty string stay valid.
    Timeline(**{**base, "color_grade": "warm_bright"})
    Timeline(**{**base, "color_grade": ""})
