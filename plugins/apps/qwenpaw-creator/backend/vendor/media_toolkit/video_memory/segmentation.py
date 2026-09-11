# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches
"""Phase 1 scene-cut segmentation planning (HLS frame-diff).

Vendored from Qwen-MM-Plugins commit 077aea6
(src/capabilities/video-memory/skill/script/build_memory/build_graph.py,
Phase 1: ``step1_scene_detect_segmentation`` + ``_find_optimal_threshold``).
License: Apache-2.0; see backend/vendor/NOTICE.md.
Modifications: ffmpeg frame extraction and checkpoint IO stay in the
Creator service; the OpenCV BGR→HLS conversion is re-implemented with
Pillow + NumPy on the same 8-bit value scale (H in [0,180), L/S in
[0,255]); the planning core is kept verbatim as pure functions.
"""

from __future__ import annotations

import io
import logging

import numpy as np
from PIL import Image

logger = logging.getLogger("creator.vendor.video_memory")

# Fallback threshold when auto-select yields none. 27.0 is the value
# PySceneDetect's ContentDetector uses as its default; this module does NOT
# depend on PySceneDetect — segmentation is a custom HLS frame-diff detector.
DEFAULT_SCENE_THRESHOLD = 27.0


def decode_jpeg_to_hls(jpeg_bytes: bytes) -> np.ndarray | None:
    """Decode JPEG bytes into an OpenCV-scale HLS float32 array."""
    try:
        with Image.open(io.BytesIO(jpeg_bytes)) as image:
            rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    except Exception:  # pylint: disable=broad-except
        return None
    v_max = rgb.max(axis=2)
    v_min = rgb.min(axis=2)
    delta = v_max - v_min
    lightness = (v_max + v_min) / 2.0
    with np.errstate(divide="ignore", invalid="ignore"):
        saturation = np.where(
            delta == 0,
            0.0,
            np.where(
                lightness < 0.5,
                delta / np.maximum(v_max + v_min, 1e-12),
                delta / np.maximum(2.0 - (v_max + v_min), 1e-12),
            ),
        )
        r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
        safe_delta = np.maximum(delta, 1e-12)
        hue = np.where(
            delta == 0,
            0.0,
            np.where(
                v_max == r,
                (60.0 * (g - b) / safe_delta) % 360.0,
                np.where(
                    v_max == g,
                    120.0 + 60.0 * (b - r) / safe_delta,
                    240.0 + 60.0 * (r - g) / safe_delta,
                ),
            ),
        )
    hls = np.empty_like(rgb)
    hls[:, :, 0] = hue / 2.0
    hls[:, :, 1] = lightness * 255.0
    hls[:, :, 2] = saturation * 255.0
    return hls.astype(np.float32)


def compute_cut_scores(
    hls_frames: list[tuple[float, np.ndarray]],
) -> tuple[list[float], list[float]]:
    """Return (cut_times, cut_scores) for consecutive HLS frame pairs."""
    w_hue, w_sat, w_lum = 1.0, 1.0, 1.0
    cut_times: list[float] = []
    cut_scores: list[float] = []
    for i in range(1, len(hls_frames)):
        _ts_prev, hls_prev = hls_frames[i - 1]
        ts_curr, hls_curr = hls_frames[i]
        if hls_prev.shape != hls_curr.shape:
            continue
        delta_h = float(np.mean(np.abs(hls_curr[:, :, 0] - hls_prev[:, :, 0])))
        delta_l = float(np.mean(np.abs(hls_curr[:, :, 1] - hls_prev[:, :, 1])))
        delta_s = float(np.mean(np.abs(hls_curr[:, :, 2] - hls_prev[:, :, 2])))
        score = delta_h * w_hue + delta_l * w_lum + delta_s * w_sat
        cut_times.append(ts_curr)
        cut_scores.append(score)
    return cut_times, cut_scores


def find_optimal_threshold(
    cut_times: list[float],
    cut_scores: list[float],
    start_sec: float,
    end_sec: float,
    min_scene_sec: float,
    max_scene_sec: float,
) -> float:
    """Binary search for threshold that produces segments with median
    duration near (min+max)/2."""
    target_median = (min_scene_sec + max_scene_sec) / 2
    unique_scores = sorted(set(cut_scores))
    if not unique_scores:
        return DEFAULT_SCENE_THRESHOLD

    def _simulate(thresh: float) -> float:
        boundaries = [t for t, s in zip(cut_times, cut_scores) if s >= thresh]
        merged: list[float] = []
        last = start_sec
        for b in boundaries:
            if b - last >= min_scene_sec:
                merged.append(b)
                last = b
        prev = start_sec
        durations = []
        for b in merged:
            durations.append(b - prev)
            prev = b
        durations.append(end_sec - prev)
        if not durations:
            return float("inf")
        durations.sort()
        return durations[len(durations) // 2]

    lo, hi = 0, len(unique_scores) - 1
    best_thresh = unique_scores[0]
    best_diff = float("inf")

    while lo <= hi:
        mid = (lo + hi) // 2
        thresh = unique_scores[mid]
        median = _simulate(thresh)
        diff = abs(median - target_median)
        if diff < best_diff:
            best_diff = diff
            best_thresh = thresh
        if median < target_median:
            lo = mid + 1
        else:
            hi = mid - 1

    logger.info(
        "auto threshold: %.1f (target median=%.0fs, actual median=%.0fs)",
        best_thresh,
        target_median,
        _simulate(best_thresh),
    )
    return best_thresh


def plan_segments(
    cut_times: list[float],
    cut_scores: list[float],
    *,
    start_sec: float,
    end_sec: float,
    min_scene_sec: float = 30.0,
    max_scene_sec: float = 300.0,
    threshold: float = 0,
) -> list[tuple[float, float]]:
    """Turn frame-diff scores into final segment ranges (Phase 1 core)."""
    if threshold <= 0 and cut_times:
        threshold = find_optimal_threshold(
            cut_times,
            cut_scores,
            start_sec,
            end_sec,
            min_scene_sec,
            max_scene_sec,
        )
    elif threshold <= 0:
        threshold = DEFAULT_SCENE_THRESHOLD

    boundaries = [t for t, s in zip(cut_times, cut_scores) if s >= threshold]

    merged_boundaries: list[float] = []
    last_b = start_sec
    for b in boundaries:
        if b - last_b >= min_scene_sec:
            merged_boundaries.append(b)
            last_b = b

    final_segments: list[tuple[float, float]] = []
    prev = start_sec
    for b in merged_boundaries:
        seg_dur = b - prev
        if seg_dur > max_scene_sec:
            n_parts = max(2, round(seg_dur / (max_scene_sec * 0.7)))
            part_dur = seg_dur / n_parts
            for j in range(n_parts):
                ps = prev + j * part_dur
                pe = prev + (j + 1) * part_dur if j < n_parts - 1 else b
                final_segments.append((ps, pe))
        else:
            final_segments.append((prev, b))
        prev = b

    last_dur = end_sec - prev
    if last_dur > max_scene_sec:
        n_parts = max(2, round(last_dur / (max_scene_sec * 0.7)))
        part_dur = last_dur / n_parts
        for j in range(n_parts):
            ps = prev + j * part_dur
            pe = prev + (j + 1) * part_dur if j < n_parts - 1 else end_sec
            final_segments.append((ps, pe))
    elif final_segments and last_dur < min_scene_sec:
        s, _ = final_segments.pop()
        final_segments.append((s, end_sec))
    else:
        final_segments.append((prev, end_sec))

    if not final_segments:
        final_segments = [(start_sec, end_sec)]
    return final_segments
