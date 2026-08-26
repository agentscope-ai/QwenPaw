# -*- coding: utf-8 -*-
"""Cut / scene / freeze detection over the frame-difference curve.

Algorithm ported from APE-benchmark ``grader/objective/program.py``
(``build_video_index`` / ``cut_detection``): the mean absolute pixel
difference between adjacent frames forms a change curve; a cut needs a
peak that is both 1.8x its 8-frame local mean (relative criterion, keeps
high-motion footage from false-firing) and at least 4.0 absolute (keeps
static footage noise out); peaks within 3 frames merge into one
transition. Freeze segments are the inverse read: diff < 2.0 sustained
for >= 5 frames.

Everything here locates and measures — it never judges. A cut count that
disagrees with the plan or a freeze segment near the tail may be entirely
legitimate (dissolves, deliberate hold frames); downstream reviewers get
these numbers as facts and decide in context.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from services.run_review.objective.media_io import GraySamples

# APE cut_detection constants (grader/objective/program.py).
_LOCAL_WINDOW = 8
_REL_PEAK_FACTOR = 1.8
_ABS_MIN_PEAK = 4.0
_TRANSITION_MERGE = 3
# APE build_video_index freeze constants.
_FREEZE_DIFF_THRESHOLD = 2.0
_FREEZE_MIN_FRAMES = 5
# Dynamic-richness read used by the camera-motion facts.
_STILL_DIFF_THRESHOLD = 0.8


def frame_diffs(samples: GraySamples) -> np.ndarray:
    """Mean absolute inter-frame difference, one value per frame gap."""
    frames = samples.frames.astype(np.float32)
    return np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))


def _detect_cut_indexes(diffs: np.ndarray) -> list[int]:
    cuts: list[int] = []
    count = diffs.shape[0]
    for index in range(count):
        value = float(diffs[index])
        if value < _ABS_MIN_PEAK:
            continue
        lo = max(0, index - _LOCAL_WINDOW)
        hi = min(count, index + _LOCAL_WINDOW + 1)
        window = np.concatenate((diffs[lo:index], diffs[index + 1 : hi]))
        local_mean = float(window.mean()) if window.size else 0.0
        if value < _REL_PEAK_FACTOR * max(local_mean, 1e-6):
            continue
        if cuts and index - cuts[-1] <= _TRANSITION_MERGE:
            if value > float(diffs[cuts[-1]]):
                cuts[-1] = index
            continue
        cuts.append(index)
    return cuts


def _freeze_segments(
    diffs: np.ndarray,
    timestamps_ms: tuple[int, ...],
) -> list[dict[str, int]]:
    segments: list[dict[str, int]] = []
    run_start: int | None = None
    for index, value in enumerate(diffs):
        if float(value) < _FREEZE_DIFF_THRESHOLD:
            if run_start is None:
                run_start = index
            continue
        if run_start is not None and index - run_start >= _FREEZE_MIN_FRAMES:
            segments.append(
                {
                    "start_ms": timestamps_ms[run_start],
                    "end_ms": timestamps_ms[index],
                },
            )
        run_start = None
    if (
        run_start is not None
        and diffs.shape[0] - run_start >= _FREEZE_MIN_FRAMES
    ):
        segments.append(
            {
                "start_ms": timestamps_ms[run_start],
                "end_ms": timestamps_ms[-1],
            },
        )
    return segments


def build_video_index(
    samples: GraySamples,
    *,
    diffs: np.ndarray | None = None,
) -> dict[str, Any]:
    """Structured motion index of one video (facts only, no verdicts)."""
    if diffs is None:
        diffs = frame_diffs(samples)
    timestamps = samples.timestamps_ms
    cut_indexes = _detect_cut_indexes(diffs)
    # diffs[i] sits between frame i and i+1; the cut lands on frame i+1.
    cut_points_ms = [timestamps[index + 1] for index in cut_indexes]
    boundaries = [timestamps[0], *cut_points_ms, timestamps[-1]]
    scenes = [
        {"start_ms": boundaries[index], "end_ms": boundaries[index + 1]}
        for index in range(len(boundaries) - 1)
        if boundaries[index + 1] > boundaries[index]
    ]
    dynamic_ratio = float(
        (diffs >= _STILL_DIFF_THRESHOLD).sum() / max(1, diffs.shape[0]),
    )
    return {
        "sampled_frames": samples.count,
        # Last sampled timestamp, NOT the container duration: naming it
        # "duration" made the VLM read a short sampling span as a short
        # video (machine_params carries the real length).
        "sampled_span_ms": timestamps[-1],
        "cut_points_ms": cut_points_ms,
        "cut_count": len(cut_points_ms),
        "scenes": scenes,
        "freeze_segments": _freeze_segments(diffs, timestamps),
        "diff_mean": round(float(diffs.mean()), 3),
        "diff_max": round(float(diffs.max()), 3),
        "dynamic_frame_ratio": round(dynamic_ratio, 3),
    }


__all__ = ["build_video_index", "frame_diffs"]
