# -*- coding: utf-8 -*-
"""Vendored video-memory segmentation planning tests."""
from __future__ import annotations

import numpy as np

from vendor.mm_plugins.video_memory.segmentation import (
    compute_cut_scores,
    decode_jpeg_to_hls,
    find_optimal_threshold,
    plan_segments,
)


def _frame(color: tuple[int, int, int]) -> np.ndarray:
    import io

    from PIL import Image

    image = Image.new("RGB", (32, 18), color)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    hls = decode_jpeg_to_hls(buffer.getvalue())
    assert hls is not None
    return hls


def test_cut_scores_spike_on_scene_change() -> None:
    red = _frame((200, 30, 30))
    blue = _frame((30, 30, 200))
    frames = [(0.0, red), (4.0, red), (8.0, blue), (12.0, blue)]
    cut_times, cut_scores = compute_cut_scores(frames)
    assert cut_times == [4.0, 8.0, 12.0]
    assert cut_scores[1] > cut_scores[0] * 10
    assert cut_scores[1] > cut_scores[2] * 10


def test_plan_segments_covers_full_range_and_respects_min_scene() -> None:
    # One strong cut at 100s; weak noise elsewhere.
    cut_times = [float(t) for t in range(4, 300, 4)]
    cut_scores = [40.0 if t == 100 else 1.0 for t in cut_times]
    segments = plan_segments(
        cut_times,
        cut_scores,
        start_sec=0.0,
        end_sec=300.0,
        min_scene_sec=30.0,
        max_scene_sec=300.0,
        threshold=20.0,
    )
    assert segments[0][0] == 0.0
    assert segments[-1][1] == 300.0
    # Contiguous coverage without gaps.
    for left, right in zip(segments, segments[1:]):
        assert left[1] == right[0]
    assert any(abs(start - 100.0) < 1e-6 for start, _ in segments)
    assert all(end - start >= 30.0 - 1e-6 for start, end in segments)


def test_plan_segments_splits_overlong_segments() -> None:
    segments = plan_segments(
        [],
        [],
        start_sec=0.0,
        end_sec=1200.0,
        min_scene_sec=30.0,
        max_scene_sec=300.0,
        threshold=20.0,
    )
    assert segments[0][0] == 0.0
    assert segments[-1][1] == 1200.0
    assert all(end - start <= 300.0 + 1e-6 for start, end in segments)
    assert len(segments) >= 4


def test_find_optimal_threshold_targets_median_duration() -> None:
    cut_times = [float(t) for t in range(10, 1200, 10)]
    cut_scores = [30.0 if t % 120 == 0 else 5.0 for t in cut_times]
    threshold = find_optimal_threshold(
        cut_times,
        cut_scores,
        0.0,
        1200.0,
        min_scene_sec=30.0,
        max_scene_sec=300.0,
    )
    # Only the strong cuts (every 120s) produce a median close to the
    # (min+max)/2 target, so the search must keep the 30-point cuts.
    assert 5.0 < threshold <= 30.0
