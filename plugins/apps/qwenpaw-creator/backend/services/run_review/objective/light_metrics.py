# -*- coding: utf-8 -*-
"""Light single-pass statistics: sharpness / stability / color warmth.

Ported from APE-benchmark ``grader/objective/program.py`` (``sharpness``
/ ``frame_stability`` / ``color_warmth``): sharpness is the variance of
the Laplacian response squashed through a sigmoid, stability is the
dispersion of the inter-frame change curve, warmth is the warm-hue pixel
ratio. All are reference numbers injected into reviewer prompts — a low
saturation may be a deliberate film look, a low sharpness a soft-focus
choice; none of these produce findings on their own.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from services.run_review.objective.media_io import GraySamples

# APE sharpness sigmoid: 1 / (1 + e^(-0.005 * (laplacian_var - 500))).
_SHARPNESS_SIGMOID_CENTER = 500.0
_SHARPNESS_SIGMOID_SLOPE = 0.005
_WARM_HUE_MAX_DEG = 70.0
_WARM_HUE_MIN_DEG = 320.0


def laplacian_variance(gray: np.ndarray) -> float:
    """Variance of the 4-neighbour Laplacian response of one frame.

    Frames thinner than three pixels leave the stencil empty, whose
    variance is NaN — and these facts are serialized into the report,
    where NaN is not valid JSON.
    """
    frame = gray.astype(np.float32)
    if frame.shape[0] < 3 or frame.shape[1] < 3:
        return 0.0
    lap = (
        frame[:-2, 1:-1]
        + frame[2:, 1:-1]
        + frame[1:-1, :-2]
        + frame[1:-1, 2:]
        - 4.0 * frame[1:-1, 1:-1]
    )
    variance = float(lap.var())
    return variance if math.isfinite(variance) else 0.0


def sharpness_facts(frames: list[np.ndarray]) -> dict[str, Any]:
    """Laplacian sharpness over a handful of representative frames."""
    variances = [laplacian_variance(frame) for frame in frames if frame.size]
    if not variances:
        return {"measured": False}
    mean_var = sum(variances) / len(variances)
    score = 1.0 / (
        1.0
        + float(
            np.exp(
                -_SHARPNESS_SIGMOID_SLOPE
                * (mean_var - _SHARPNESS_SIGMOID_CENTER),
            ),
        )
    )
    return {
        "measured": True,
        "laplacian_variance_mean": round(mean_var, 1),
        "sigmoid_score": round(score, 3),
    }


def stability_facts(diffs: np.ndarray) -> dict[str, Any]:
    """Dispersion of the change curve — high spikes hint at flicker."""
    if diffs.size == 0:
        return {"measured": False}
    mean = float(diffs.mean())
    std = float(diffs.std())
    return {
        "measured": True,
        "diff_mean": round(mean, 3),
        "diff_std": round(std, 3),
        "variation_coefficient": round(std / max(mean, 1e-6), 3),
    }


def _rgb_to_hue_sat(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    pixels = rgb.reshape(-1, 3).astype(np.float32) / 255.0
    max_c = pixels.max(axis=1)
    min_c = pixels.min(axis=1)
    delta = max_c - min_c
    hue = np.zeros_like(max_c)
    red, green, blue = pixels[:, 0], pixels[:, 1], pixels[:, 2]
    mask = delta > 1e-6
    red_max = mask & (max_c == red)
    green_max = mask & (max_c == green) & ~red_max
    blue_max = mask & ~red_max & ~green_max
    hue[red_max] = (green[red_max] - blue[red_max]) / delta[red_max] % 6.0
    hue[green_max] = (blue[green_max] - red[green_max]) / delta[
        green_max
    ] + 2.0
    hue[blue_max] = (red[blue_max] - green[blue_max]) / delta[blue_max] + 4.0
    hue *= 60.0
    saturation = np.where(max_c > 1e-6, delta / np.maximum(max_c, 1e-6), 0.0)
    return hue, saturation


def color_facts(rgb_frames: list[np.ndarray]) -> dict[str, Any]:
    """Warm-hue ratio and mean saturation over sampled RGB frames."""
    if not rgb_frames:
        return {"measured": False}
    warm_ratios: list[float] = []
    saturations: list[float] = []
    for frame in rgb_frames:
        hue, saturation = _rgb_to_hue_sat(frame)
        colored = saturation > 0.15
        if colored.sum() == 0:
            warm_ratios.append(0.0)
        else:
            warm = colored & (
                (hue <= _WARM_HUE_MAX_DEG) | (hue >= _WARM_HUE_MIN_DEG)
            )
            warm_ratios.append(float(warm.sum()) / float(colored.sum()))
        saturations.append(float(saturation.mean()))
    return {
        "measured": True,
        "warm_hue_ratio": round(sum(warm_ratios) / len(warm_ratios), 3),
        "saturation_mean": round(sum(saturations) / len(saturations), 3),
    }


def representative_gray_frames(
    samples: GraySamples,
    *,
    count: int = 3,
) -> list[np.ndarray]:
    """Evenly spread frames for the single-frame statistics."""
    if samples.count == 0:
        return []
    indexes = np.linspace(0, samples.count - 1, num=count, dtype=int)
    return [samples.frames[index] for index in dict.fromkeys(indexes)]


__all__ = [
    "color_facts",
    "laplacian_variance",
    "representative_gray_frames",
    "sharpness_facts",
    "stability_facts",
]
