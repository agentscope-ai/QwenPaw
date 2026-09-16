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
    SCENE_REVIEW_CHECKS,
)

pytestmark = pytest.mark.unit

_FFMPEG = shutil.which("ffmpeg")
requires_ffmpeg = pytest.mark.skipif(_FFMPEG is None, reason="needs ffmpeg")


def test_vendored_rubrics_stay_verbatim() -> None:
    names = [row.name for row in APPEAL_RUBRIC_ROWS]
    assert names == (
        "Concept|Contract adherence|Rhythm|Restraint|Craft quality|"
        "Sound|Typography & motion"
    ).split("|")
    # Concept carried veto power upstream; Creator keeps the flag only.
    vetoes = [row.key for row in APPEAL_RUBRIC_ROWS if row.upstream_veto]
    assert vetoes == ["concept"]
    assert "Hook inside 1.5s" in APPEAL_RUBRIC_ROWS[2].anchor_questions
    assert [check.key for check in SCENE_REVIEW_CHECKS] == (
        "devices type_fonts composition_safety "
        "motion_quality technical watch_once"
    ).split()


def _make_clip(path: Path, *, interior_black: bool, silent: bool) -> None:
    audio = (
        "anullsrc=r=44100:cl=mono:d=3"
        if silent
        else "sine=frequency=440:sample_rate=44100:d=3"
    )
    command = [_FFMPEG, "-y", "-hide_banner", "-nostats", "-f", "lavfi"]
    command += ["-i", "color=c=red:s=192x108:d=3"]
    command += ["-f", "lavfi", "-i", audio, "-shortest"]
    command += ["-pix_fmt", "yuv420p"]
    if interior_black:
        command += [
            "-vf",
            "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:"
            "enable='between(t,1,2)'",
        ]
    command.append(str(path))
    subprocess.run(command, check=True, capture_output=True, timeout=120)


@requires_ffmpeg
def test_gates_emit_evidence_and_flag_interior_black(tmp_path: Path) -> None:
    clip = tmp_path / "black.mp4"
    _make_clip(clip, interior_black=True, silent=False)
    block = review_gates.run_review_gates(clip)
    assert [gate.name for gate in block.gates] == [
        "ffprobe",
        "loudness",
        "black",
    ]
    assert len(block.sha1_head12) == 12
    assert block.passed is False
    black = next(gate for gate in block.gates if gate.name == "black")
    gap = black.metrics["interior_gaps"][0]
    assert 0.5 < gap["start"] < 1.5


@requires_ffmpeg
def test_loudness_flags_silence_and_clean_clip_passes(tmp_path: Path) -> None:
    silent = tmp_path / "silent.mp4"
    _make_clip(silent, interior_black=False, silent=True)
    result = review_gates.loudness_gate(silent)
    assert result.passed is False
    assert result.metrics.get("digital_silence") or result.metrics.get(
        "effectively_silent",
    )
    # A clean clip passes the black gate and yields judgeable stats.
    clip = tmp_path / "red.mp4"
    _make_clip(clip, interior_black=False, silent=False)
    assert review_gates.black_gate(clip).passed is True
    stats = frame_stats.sample_stats(clip)
    assert set(stats) == {"y_mean", "y_range", "sat_mean"}
    judgment = frame_stats.judge_stats(stats)
    assert set(judgment) == {"exposure", "contrast", "saturation"}
