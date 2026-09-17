# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import subprocess

import pytest

from services.runtime_files import media_probe


def test_ffprobe_json_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "streams": [
            {"codec_type": "video", "width": 1920, "height": 1080},
            {
                "codec_type": "audio",
                "sample_rate": "48000",
                "channels": 2,
            },
        ],
        "format": {"duration": "12.345"},
    }
    monkeypatch.setattr(
        media_probe.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["ffprobe"],
            0,
            json.dumps(payload),
            "",
        ),
    )

    result = media_probe.probe_media(
        "clip.mp4",
        ffmpeg_path="/tools/ffmpeg",
        ffprobe_path="/tools/ffprobe",
    )

    assert result == media_probe.MediaProbe(
        duration_seconds=12.345,
        width=1920,
        height=1080,
        sample_rate_hz=48000,
        channels=2,
        has_audio=True,
        source="ffprobe",
    )


def test_bundled_ffmpeg_fallback_probes_without_ffprobe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(media_probe, "resolve_ffprobe", lambda **_kwargs: None)
    diagnostic = """
Duration: 00:01:02.50, start: 0.000000, bitrate: 1200 kb/s
Stream #0:0: Video: h264, yuv420p, 1280x720, 30 fps
Stream #0:1: Audio: aac, 48000 Hz, stereo, fltp
"""
    monkeypatch.setattr(
        media_probe.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["ffmpeg"],
            1,
            "",
            diagnostic,
        ),
    )

    result = media_probe.probe_media("clip.mp4", ffmpeg_path="/tools/ffmpeg")

    assert result.duration_seconds == 62.5
    assert (result.width, result.height) == (1280, 720)
    assert result.sample_rate_hz == 48000
    assert result.channels == 2
    assert result.has_audio
    assert result.source == "ffmpeg"


def test_ffmpeg_fallback_runs_after_ffprobe_rejects_media(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(command[0])
        if command[0].endswith("ffprobe"):
            return subprocess.CompletedProcess(command, 1, "", "probe error")
        return subprocess.CompletedProcess(
            command,
            1,
            "",
            "Duration: 00:00:03.00\nStream #0:0: Video: h264, 640x360",
        )

    monkeypatch.setattr(media_probe.subprocess, "run", run)

    result = media_probe.probe_media(
        "clip.mp4",
        ffmpeg_path="/tools/ffmpeg",
        ffprobe_path="/tools/ffprobe",
    )

    assert calls == ["/tools/ffprobe", "/tools/ffmpeg"]
    assert result.duration_seconds == 3.0
    assert result.source == "ffmpeg"


def test_probe_reports_when_both_executables_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(media_probe, "resolve_ffprobe", lambda **_kwargs: None)
    monkeypatch.setattr(media_probe, "resolve_ffmpeg", lambda: None)

    with pytest.raises(media_probe.MediaProbeUnavailable):
        media_probe.probe_media("clip.mp4")
