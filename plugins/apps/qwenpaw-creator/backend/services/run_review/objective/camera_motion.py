# -*- coding: utf-8 -*-
"""Camera-motion quality facts (optical flow, cv2-optional).

Ported from APE-benchmark ``grader/objective/camera_motion.py``: dense
optical flow per frame pair, aggregated as direction consistency (40%,
circular variance of flow angles — a push should diverge, a pan should
translate uniformly), magnitude smoothness (35%, variation coefficient
of per-frame mean magnitudes) and dynamic richness (25%, non-still frame
ratio).

Without cv2 the flow-based components are skipped and only the dynamic
richness (from the frame-difference curve) is reported. A static shot
may be a deliberate locked-off composition — these numbers are reference
evidence for the motion_quality check, never findings by themselves.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from services.run_review.objective.media_io import GraySamples

try:  # pragma: no cover - environment-dependent optional dependency
    import cv2  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    cv2 = None

# APE camera_motion.py weights and reads.
_WEIGHT_DIRECTION = 0.40
_WEIGHT_SMOOTHNESS = 0.35
_WEIGHT_DYNAMIC = 0.25
_DYNAMIC_FULL_RATIO = 0.60
_FLOW_STILL_MAGNITUDE = 0.15
_MAX_FLOW_PAIRS = 120


def _flow_stats(samples: GraySamples) -> tuple[list[float], list[float]]:
    """Per-pair (mean magnitude, direction circular variance)."""
    magnitudes: list[float] = []
    circular_variances: list[float] = []
    stride = max(1, samples.count // _MAX_FLOW_PAIRS)
    for index in range(0, samples.count - stride, stride):
        # Decoded frames are views over a read-only ffmpeg buffer; the
        # OpenCV bindings need writable, contiguous input.
        flow = cv2.calcOpticalFlowFarneback(
            np.ascontiguousarray(samples.frames[index]),
            np.ascontiguousarray(samples.frames[index + stride]),
            None,
            pyr_scale=0.5,
            levels=2,
            winsize=15,
            iterations=2,
            poly_n=5,
            poly_sigma=1.1,
            flags=0,
        )
        fx, fy = flow[..., 0], flow[..., 1]
        magnitude = np.sqrt(fx * fx + fy * fy)
        mean_mag = float(magnitude.mean())
        magnitudes.append(mean_mag)
        moving = magnitude > _FLOW_STILL_MAGNITUDE
        if moving.sum() < 16:
            circular_variances.append(0.0)
            continue
        angles = np.arctan2(fy[moving], fx[moving])
        weights = magnitude[moving]
        resultant = np.sqrt(
            (np.cos(angles) * weights).sum() ** 2
            + (np.sin(angles) * weights).sum() ** 2,
        ) / max(float(weights.sum()), 1e-6)
        circular_variances.append(float(1.0 - resultant))
    return magnitudes, circular_variances


def camera_motion_facts(
    samples: GraySamples,
    *,
    dynamic_frame_ratio: float,
) -> dict[str, Any]:
    """Direction / smoothness / dynamic facts for one video."""
    dynamic_score = min(1.0, dynamic_frame_ratio / _DYNAMIC_FULL_RATIO)
    if cv2 is None:
        return {
            "measured": "partial",
            "skip_reason": "opencv 未安装：方向一致性/平滑度跳过",
            "dynamic_frame_ratio": round(dynamic_frame_ratio, 3),
            "dynamic_score": round(dynamic_score, 3),
        }
    magnitudes, circular_variances = _flow_stats(samples)
    if not magnitudes:
        return {
            "measured": False,
            "note": "视频过短，光流无从测量",
        }
    moving_pairs = [
        (mag, var)
        for mag, var in zip(magnitudes, circular_variances)
        if mag > _FLOW_STILL_MAGNITUDE
    ]
    if moving_pairs:
        direction_consistency = 1.0 - float(
            np.mean([var for _, var in moving_pairs]),
        )
        moving_mags = np.array([mag for mag, _ in moving_pairs])
        smoothness = 1.0 - min(
            1.0,
            float(moving_mags.std() / max(float(moving_mags.mean()), 1e-6)),
        )
    else:
        direction_consistency = 1.0
        smoothness = 1.0
    composite = (
        _WEIGHT_DIRECTION * direction_consistency
        + _WEIGHT_SMOOTHNESS * smoothness
        + _WEIGHT_DYNAMIC * dynamic_score
    )
    return {
        "measured": True,
        "direction_consistency": round(direction_consistency, 3),
        "magnitude_smoothness": round(smoothness, 3),
        "dynamic_frame_ratio": round(dynamic_frame_ratio, 3),
        "dynamic_score": round(dynamic_score, 3),
        "composite_score": round(composite, 3),
        "note": "静止镜头可能是刻意定机位，低动态不构成缺陷",
    }


__all__ = ["camera_motion_facts"]
