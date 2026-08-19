# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Freeze-frame padding must never reference a missing audio stream."""
from __future__ import annotations

import pytest

from services.media_files.local_execution import FfmpegLocalMediaRunner


pytestmark = pytest.mark.unit


def _filter(**kwargs: object) -> str:
    return FfmpegLocalMediaRunner._placement_filter(
        None,
        canvas_size=(1280, 720),
        duration_seconds=6.0,
        **kwargs,
    )


def test_no_freeze_keeps_plain_video_chain():
    chain = _filter()
    assert "tpad" not in chain
    assert "[0:a]" not in chain


def test_freeze_with_audio_pads_both_video_and_audio():
    chain = _filter(freeze_duration=2.0, freeze_audio=True)
    assert "tpad=stop_mode=clone:stop_duration=2.000000" in chain
    assert "[0:a]apad=pad_dur=2.000000[a]" in chain


def test_freeze_without_audio_never_references_the_audio_stream():
    """Generated R2V footage usually has no audio track; referencing [0:a]
    would make ffmpeg reject the whole filtergraph."""

    chain = _filter(freeze_duration=2.0, freeze_audio=False)
    assert "tpad=stop_mode=clone:stop_duration=2.000000" in chain
    assert "[0:a]" not in chain
