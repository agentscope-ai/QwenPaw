# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Tests for beat_grid (WT-B5) and grounding crop-zoom (WT-A4)."""

from __future__ import annotations

import asyncio
import io
import sys

import pytest
from PIL import Image

from services import object_grounding
from services.media_files.beat_grid import (
    BeatGrid,
    BeatGridUnavailable,
    extract_beat_grid,
)

pytestmark = pytest.mark.unit

# ── beat grid ────────────────────────────────────────────────────────────────


def test_snap_within_tolerance_moves_to_the_beat() -> None:
    grid = BeatGrid(beats_ms=(0, 500, 1000, 1500), tempo_bpm=120.0)
    assert grid.snap_ms(480) == 500
    assert grid.snap_ms(1240) == 1240, "beyond tolerance stays untouched"
    assert grid.snap_ms(1490) == 1500


def test_beat_snapped_span_shifts_decorations_forward_only() -> None:
    from services.media_files.motion_design import _beat_snapped_span
    from services.project_files.models import TimelineSpan

    grid = BeatGrid(beats_ms=(0, 500, 1000), tempo_bpm=120.0)
    span = TimelineSpan(start_tick=880, duration_tick=2000)
    # 880ms → next beat 1000ms; the end (2880) stays fixed.
    snapped = _beat_snapped_span(span, (grid, 0), 1000)
    assert snapped.start_tick == 1000
    assert snapped.duration_tick == 1880
    # A backward-only snap (1100 → 1000) is refused: forward shifts only.
    unchanged = _beat_snapped_span(
        TimelineSpan(start_tick=1100, duration_tick=2000),
        (grid, 0),
        1000,
    )
    assert unchanged.start_tick == 1100
    # No grid → pass-through.
    assert _beat_snapped_span(span, None, 1000) is span


def test_missing_librosa_is_declared(tmp_path, monkeypatch) -> None:
    audio = tmp_path / "bgm.wav"
    audio.write_bytes(b"RIFF")
    monkeypatch.setitem(sys.modules, "librosa", None)
    # ``import librosa`` finds the None sentinel and raises ImportError.
    with pytest.raises(BeatGridUnavailable, match="librosa"):
        extract_beat_grid(audio)


# ── crop-zoom re-observation ─────────────────────────────────────────────────


def _image_bytes(width: int = 1000, height: int = 800) -> bytes:
    image = Image.new("RGB", (width, height), (200, 200, 200))
    # A red target patch at the normalized center-right (600-700, 300-400).
    for x in range(600, 700):
        for y in range(240, 320):
            image.putpixel((x, y), (255, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_crop_region_expands_clamps_and_upscales() -> None:
    content = _image_bytes()
    cropped = object_grounding.crop_region_bytes(content, [600, 300, 700, 400])
    image = Image.open(io.BytesIO(cropped))
    # Upscaled so the short side reaches the observation floor.
    assert min(image.size) >= object_grounding.CROP_MIN_SHORT_SIDE
    # Expansion keeps the aspect ratio of the expanded (not raw) box.
    assert image.size[0] > 0 and image.size[1] > 0

    # A box touching the frame edge clamps instead of failing.
    edge = object_grounding.crop_region_bytes(content, [0, 0, 100, 100])
    assert Image.open(io.BytesIO(edge)).size[0] > 0


def test_crop_and_observe_uploads_and_asks(monkeypatch) -> None:
    content = _image_bytes()
    uploads: list[bytes] = []

    async def fake_upload(data: bytes) -> str:
        uploads.append(data)
        return "https://example.invalid/crop.jpg"

    async def fake_chat(parts, **_kwargs):
        assert parts[0]["type"] == "video_url" or "image" in str(parts[0])
        return "放大后可见红色标记块。"

    monkeypatch.setattr(
        object_grounding.vlm_model,
        "multimodal_media_part",
        lambda url, kind: {"type": "image_url", "image_url": {"url": url}},
    )
    monkeypatch.setattr(
        object_grounding.vlm_model,
        "chat_completion",
        fake_chat,
    )
    monkeypatch.setattr(
        object_grounding.model_config,
        "get_vlm_timeout_seconds",
        lambda: 60,
    )
    monkeypatch.setattr(
        object_grounding.model_config,
        "get_vlm_model_name",
        lambda: "qwen3.7-plus",
    )

    result = asyncio.run(
        object_grounding.crop_region_and_observe(
            content,
            [600, 300, 700, 400],
            "标记块是什么颜色？",
            upload_url_for=fake_upload,
        ),
    )
    assert uploads, "the cropped bytes must be uploaded"
    assert "红色" in result["answer"]
    assert result["bbox2d"] == [600, 300, 700, 400]
