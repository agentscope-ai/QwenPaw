# -*- coding: utf-8 -*-
# pylint: disable=subprocess-run-check
from __future__ import annotations

import json
import shutil
import subprocess


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def probe_duration_seconds(media_path: str) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            media_path,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        return 0.0
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return 0.0


def assert_playable(media_path: str, min_duration: float = 0.5) -> float:
    assert ffprobe_available(), "本机缺少 ffprobe，无法校验成片"
    duration = probe_duration_seconds(media_path)
    assert (
        duration >= min_duration
    ), f"成片时长 {duration}s 低于阈值 {min_duration}s：{media_path}"
    return duration
