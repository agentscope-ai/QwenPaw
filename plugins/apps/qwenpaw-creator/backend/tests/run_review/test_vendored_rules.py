# -*- coding: utf-8 -*-
"""Vendored review rules and gates: content and behavior regression."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from vendor.media_toolkit import frame_stats, review_gates
from vendor.media_toolkit.review_rubrics import (
    APPEAL_RUBRIC_ROWS,
    COMMON_FAILURES,
    SCENE_REVIEW_CHECKS,
)

pytestmark = pytest.mark.unit

_FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(
    _FFMPEG is None,
    reason="ffmpeg is required for gate tests",
)


def test_appeal_rubric_rows_stay_verbatim() -> None:
    names = [row.name for row in APPEAL_RUBRIC_ROWS]
    assert names == [
        "Concept",
        "Contract adherence",
        "Rhythm",
        "Restraint",
        "Craft quality",
        "Sound",
        "Typography & motion",
    ]
    assert [row.index for row in APPEAL_RUBRIC_ROWS] == list(range(7))
    # Only the concept row carried veto power upstream; Creator keeps the
    # flag for provenance but never ports the gate semantics.
    assert [row.key for row in APPEAL_RUBRIC_ROWS if row.upstream_veto] == [
        "concept",
    ]
    assert "Hook inside 1.5s" in APPEAL_RUBRIC_ROWS[2].anchor_questions
    assert len(COMMON_FAILURES) >= 10


def test_scene_review_checks_stay_verbatim() -> None:
    keys = [check.key for check in SCENE_REVIEW_CHECKS]
    assert keys == [
        "devices",
        "type_fonts",
        "composition_safety",
        "motion_quality",
        "technical",
        "watch_once",
    ]
    assert [check.index for check in SCENE_REVIEW_CHECKS] == list(
        range(1, 7),
    )


def _make_clip(
    path: Path,
    *,
    interior_black: bool,
    silent: bool,
    duration: float = 3.0,
) -> None:
    video = f"color=c=red:s=192x108:d={duration}"
    filters = []
    if interior_black:
        filters.append(
            "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:"
            "enable='between(t,1,2)'",
        )
    audio = (
        f"anullsrc=r=44100:cl=mono:d={duration}"
        if silent
        else f"sine=frequency=440:sample_rate=44100:d={duration}"
    )
    command = [
        _FFMPEG,
        "-y",
        "-hide_banner",
        "-nostats",
        "-f",
        "lavfi",
        "-i",
        video,
        "-f",
        "lavfi",
        "-i",
        audio,
        "-shortest",
        "-pix_fmt",
        "yuv420p",
    ]
    if filters:
        command += ["-vf", ",".join(filters)]
    command.append(str(path))
    subprocess.run(command, check=True, capture_output=True, timeout=120)


@requires_ffmpeg
def test_black_gate_flags_interior_black(tmp_path: Path) -> None:
    clip = tmp_path / "black.mp4"
    _make_clip(clip, interior_black=True, silent=False)
    result = review_gates.black_gate(clip)
    assert result.passed is False
    assert result.metrics["interior_gaps"]
    gap = result.metrics["interior_gaps"][0]
    assert 0.5 < gap["start"] < 1.5


@requires_ffmpeg
def test_black_gate_passes_clean_clip(tmp_path: Path) -> None:
    clip = tmp_path / "clean.mp4"
    _make_clip(clip, interior_black=False, silent=False)
    result = review_gates.black_gate(clip)
    assert result.passed is True
    assert result.metrics["interior_gaps"] == []


@requires_ffmpeg
def test_loudness_gate_fails_silent_track(tmp_path: Path) -> None:
    clip = tmp_path / "silent.mp4"
    _make_clip(clip, interior_black=False, silent=True)
    result = review_gates.loudness_gate(clip)
    assert result.passed is False
    assert result.metrics["has_audio"] is True
    assert result.metrics.get("digital_silence") or result.metrics.get(
        "effectively_silent",
    )


@requires_ffmpeg
def test_run_review_gates_emits_evidence_block(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    _make_clip(clip, interior_black=True, silent=False)
    block = review_gates.run_review_gates(clip)
    assert [gate.name for gate in block.gates] == [
        "ffprobe",
        "loudness",
        "black",
    ]
    assert len(block.sha1_head12) == 12
    assert block.passed is False
    payload = block.to_dict()
    assert payload["file"] == str(clip)
    assert len(payload["gates"]) == 3


@requires_ffmpeg
def test_frame_stats_sample_and_judge(tmp_path: Path) -> None:
    clip = tmp_path / "red.mp4"
    _make_clip(clip, interior_black=False, silent=False)
    stats = frame_stats.sample_stats(clip)
    assert set(stats) == {"y_mean", "y_range", "sat_mean"}
    assert 0.0 <= stats["y_mean"] <= 1.0
    judgment = frame_stats.judge_stats(stats)
    assert set(judgment) == {"exposure", "contrast", "saturation"}


@requires_ffmpeg
def test_frame_stats_image(tmp_path: Path) -> None:
    image = tmp_path / "red.png"
    subprocess.run(
        [
            _FFMPEG,
            "-y",
            "-hide_banner",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=64x64:d=1",
            "-frames:v",
            "1",
            str(image),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    stats = frame_stats.image_stats(image)
    assert 0.0 <= stats["y_mean"] <= 1.0
