# -*- coding: utf-8 -*-
"""Vendored media tooling must honour Creator's binary contract.

Issue #8592: ``frame_stats.py`` hard-coded ``"ffmpeg"``/``"ffprobe"``, so a
host that configured ``CREATOR_FFMPEG_PATH`` (the documented dependency
contract) still failed every objective media review — and the failed
attempts consumed the slot's review budget until auto-review stopped for
good.
"""

# pylint: disable=protected-access

from __future__ import annotations

import os
import sys

import pytest

from services.runtime_files import runtime_dependencies
from vendor.media_toolkit import frame_stats, review_gates

pytestmark = pytest.mark.unit


def _executable() -> str:
    # Any absolute executable works; the resolver only checks the path.
    return sys.executable


def test_frame_stats_resolves_ffmpeg_through_the_creator_contract(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        runtime_dependencies.CREATOR_FFMPEG_PATH_ENV,
        _executable(),
    )
    # The contract wins even when nothing is on PATH.
    monkeypatch.setattr(frame_stats.shutil, "which", lambda name: None)

    assert frame_stats._require_tool("ffmpeg") == os.path.realpath(
        _executable(),
    )


def test_review_gates_resolve_ffprobe_through_the_creator_contract(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        runtime_dependencies.CREATOR_FFPROBE_PATH_ENV,
        _executable(),
    )
    monkeypatch.setattr(review_gates.shutil, "which", lambda name: None)

    assert review_gates._require_tool("ffprobe") == os.path.realpath(
        _executable(),
    )


def test_frame_stats_still_falls_back_to_path(monkeypatch) -> None:
    monkeypatch.delenv(
        runtime_dependencies.CREATOR_FFMPEG_PATH_ENV,
        raising=False,
    )
    monkeypatch.setattr(
        runtime_dependencies,
        "resolve_ffmpeg",
        lambda: None,
    )
    monkeypatch.setattr(
        frame_stats.shutil,
        "which",
        lambda name: "/usr/local/bin/ffmpeg",
    )

    assert frame_stats._require_tool("ffmpeg") == "/usr/local/bin/ffmpeg"


def test_missing_binary_fails_actionably(monkeypatch) -> None:
    monkeypatch.delenv(
        runtime_dependencies.CREATOR_FFPROBE_PATH_ENV,
        raising=False,
    )
    monkeypatch.delenv(
        runtime_dependencies.CREATOR_FFMPEG_PATH_ENV,
        raising=False,
    )
    monkeypatch.setattr(
        runtime_dependencies,
        "resolve_ffprobe",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        runtime_dependencies,
        "resolve_ffmpeg",
        lambda: None,
    )
    monkeypatch.setattr(frame_stats.shutil, "which", lambda name: None)

    with pytest.raises(frame_stats.FrameStatsError, match="ffprobe"):
        frame_stats._require_tool("ffprobe")

    with pytest.raises(review_gates.ReviewGateError, match="ffmpeg"):
        review_gates._require_tool("ffmpeg")


def test_probe_duration_uses_the_resolved_binary(
    monkeypatch,
    tmp_path,
) -> None:
    captured: dict[str, list[str]] = {}

    def fake_check_output(argv, **kwargs):
        captured["argv"] = argv
        return b"12.5\n"

    monkeypatch.setattr(
        frame_stats.subprocess,
        "check_output",
        fake_check_output,
    )
    monkeypatch.setattr(
        frame_stats,
        "_require_tool",
        lambda name: "/opt/tools/ffprobe",
    )

    assert frame_stats.probe_duration(tmp_path / "clip.mp4") == 12.5
    assert captured["argv"][0] == "/opt/tools/ffprobe"
