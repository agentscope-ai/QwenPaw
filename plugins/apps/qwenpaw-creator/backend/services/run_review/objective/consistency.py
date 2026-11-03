# -*- coding: utf-8 -*-
"""CPU cross-shot subject-consistency facts.

Ported from APE-benchmark ``grader/objective/consistency.py``: split the
video at the detected cuts, take the sharpest frame of each shot, crop
the subject region (face detection when cv2 is available, otherwise a
center crop) and compare shot pairs with three complementary metrics —
histogram correlation (< 0.5: palette/wardrobe drift), SSIM (< 0.3:
silhouette/composition drift) and Hu-moment distance (> 5.0: shape
drift). Two of three votes mark a pair as SUSPECT.

A suspect pair is a lead, not a verdict: the same character at a new
angle or in different lighting trips these metrics too. The reviewer
side renders the pair side-by-side and lets the VLM confirm before
anything becomes a finding; without a VLM the pairs are reported as
"unconfirmed suspicion" facts only.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import numpy as np

from services.run_review.objective.light_metrics import laplacian_variance
from services.run_review.objective.media_io import GraySamples
from utils.logger import setup_logger

try:  # pragma: no cover - environment-dependent optional dependency
    import cv2  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    cv2 = None

logger = setup_logger("creator.run_review.objective.consistency")

# APE consistency.py vote thresholds.
_HIST_CORR_MIN = 0.5
_SSIM_MIN = 0.3
_HU_DISTANCE_MAX = 5.0
_SUSPECT_VOTES = 2
_CENTER_CROP_RATIO = 0.6
_HIST_BINS = 64


def _center_crop(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    crop_h = int(height * _CENTER_CROP_RATIO)
    crop_w = int(width * _CENTER_CROP_RATIO)
    top = (height - crop_h) // 2
    left = (width - crop_w) // 2
    return frame[top : top + crop_h, left : left + crop_w]


@lru_cache(maxsize=1)
def _face_cascade() -> Any:
    """Parse the Haar cascade once per process (XML parse is not cheap)."""
    if (
        cv2 is None
        or not hasattr(cv2, "CascadeClassifier")
        or not hasattr(cv2, "data")
    ):  # pragma: no cover - optional/version-dependent dependency
        return None
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml",
    )
    return None if cascade.empty() else cascade


def _subject_region(frame: np.ndarray) -> tuple[np.ndarray, str]:
    """Face crop when cv2 can find one; center crop otherwise."""
    if cv2 is not None:
        try:
            cascade = _face_cascade()
            if cascade is None:
                return _center_crop(frame), "center"
            # cv2 needs writable, contiguous input; decoded frames are
            # read-only views over the ffmpeg buffer.
            faces = cascade.detectMultiScale(
                np.ascontiguousarray(frame),
                1.1,
                4,
            )
            if len(faces):
                x, y, w, h = max(faces, key=lambda box: box[2] * box[3])
                pad_w, pad_h = w // 4, h // 4
                top = max(0, y - pad_h)
                left = max(0, x - pad_w)
                return (
                    frame[top : y + h + pad_h, left : x + w + pad_w],
                    "face",
                )
        except Exception:  # pragma: no cover - defensive
            logger.exception("face detection failed; using center crop")
    return _center_crop(frame), "center"


def _hist_correlation(one: np.ndarray, two: np.ndarray) -> float:
    hist_a, _ = np.histogram(one, bins=_HIST_BINS, range=(0, 255))
    hist_b, _ = np.histogram(two, bins=_HIST_BINS, range=(0, 255))
    a = hist_a.astype(np.float64)
    b = hist_b.astype(np.float64)
    a -= a.mean()
    b -= b.mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    if denom <= 0:
        return 1.0
    return float((a * b).sum() / denom)


def _resize_to(frame: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Nearest-neighbour resize (metric inputs, quality irrelevant)."""
    rows = np.linspace(0, frame.shape[0] - 1, shape[0]).astype(int)
    cols = np.linspace(0, frame.shape[1] - 1, shape[1]).astype(int)
    return frame[np.ix_(rows, cols)]


def _global_ssim(one: np.ndarray, two: np.ndarray) -> float:
    """Single-window SSIM — coarse but monotonic for drift detection."""
    shape = (
        min(one.shape[0], two.shape[0]),
        min(one.shape[1], two.shape[1]),
    )
    if shape[0] < 8 or shape[1] < 8:
        return 1.0
    a = _resize_to(one, shape).astype(np.float64)
    b = _resize_to(two, shape).astype(np.float64)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mu_a, mu_b = a.mean(), b.mean()
    var_a, var_b = a.var(), b.var()
    cov = ((a - mu_a) * (b - mu_b)).mean()
    return float(
        ((2 * mu_a * mu_b + c1) * (2 * cov + c2))
        / ((mu_a**2 + mu_b**2 + c1) * (var_a + var_b + c2)),
    )


def _hu_moments(frame: np.ndarray) -> np.ndarray:
    """Seven Hu invariant moments of one grayscale region."""
    grid_y, grid_x = np.mgrid[: frame.shape[0], : frame.shape[1]]
    intensity = frame.astype(np.float64)
    total = intensity.sum() + 1e-10
    x_bar = (grid_x * intensity).sum() / total
    y_bar = (grid_y * intensity).sum() / total

    def mu(p: int, q: int) -> float:
        return float(
            (
                ((grid_x - x_bar) ** p) * ((grid_y - y_bar) ** q) * intensity
            ).sum(),
        )

    def eta(p: int, q: int) -> float:
        return mu(p, q) / (total ** (1 + (p + q) / 2))

    n20, n02, n11 = eta(2, 0), eta(0, 2), eta(1, 1)
    n30, n03 = eta(3, 0), eta(0, 3)
    n21, n12 = eta(2, 1), eta(1, 2)
    h1 = n20 + n02
    h2 = (n20 - n02) ** 2 + 4 * n11**2
    h3 = (n30 - 3 * n12) ** 2 + (3 * n21 - n03) ** 2
    h4 = (n30 + n12) ** 2 + (n21 + n03) ** 2
    h5 = (n30 - 3 * n12) * (n30 + n12) * (
        (n30 + n12) ** 2 - 3 * (n21 + n03) ** 2
    ) + (3 * n21 - n03) * (n21 + n03) * (
        3 * (n30 + n12) ** 2 - (n21 + n03) ** 2
    )
    h6 = (n20 - n02) * ((n30 + n12) ** 2 - (n21 + n03) ** 2) + 4 * n11 * (
        n30 + n12
    ) * (n21 + n03)
    h7 = (3 * n21 - n03) * (n30 + n12) * (
        (n30 + n12) ** 2 - 3 * (n21 + n03) ** 2
    ) - (n30 - 3 * n12) * (n21 + n03) * (
        3 * (n30 + n12) ** 2 - (n21 + n03) ** 2
    )
    return np.array([h1, h2, h3, h4, h5, h6, h7])


def _hu_distance(one: np.ndarray, two: np.ndarray) -> float:
    """cv2.matchShapes-style log-scaled Hu moment distance."""

    def log_scale(values: np.ndarray) -> np.ndarray:
        return np.sign(values) * np.log10(np.abs(values) + 1e-30)

    return float(np.abs(log_scale(one) - log_scale(two)).sum())


def _scene_representative(
    samples: GraySamples,
    scene: dict[str, int],
) -> tuple[int, np.ndarray] | None:
    """Sharpest frame (timestamp, pixels) inside one scene."""
    candidates = [
        (timestamp, samples.frames[index])
        for index, timestamp in enumerate(samples.timestamps_ms)
        if scene["start_ms"]
        <= timestamp
        < max(
            scene["end_ms"],
            scene["start_ms"] + 1,
        )
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: laplacian_variance(item[1]))


def cross_shot_consistency_facts(
    samples: GraySamples,
    scenes: list[dict[str, int]],
) -> dict[str, Any]:
    """Adjacent-shot subject comparison; suspects need VLM confirmation."""
    if len(scenes) < 2:
        return {
            "measured": False,
            "note": "不足两个镜头，跨镜一致性无从测量",
        }
    representatives: list[tuple[int, np.ndarray]] = []
    for scene in scenes:
        rep = _scene_representative(samples, scene)
        if rep is not None:
            representatives.append(rep)
    if len(representatives) < 2:
        return {"measured": False, "note": "镜头内无可用代表帧"}
    pairs: list[dict[str, Any]] = []
    suspect_count = 0
    for index in range(len(representatives) - 1):
        ts_a, frame_a = representatives[index]
        ts_b, frame_b = representatives[index + 1]
        region_a, crop_a = _subject_region(frame_a)
        region_b, _ = _subject_region(frame_b)
        hist_corr = _hist_correlation(region_a, region_b)
        ssim = _global_ssim(region_a, region_b)
        hu_dist = _hu_distance(_hu_moments(region_a), _hu_moments(region_b))
        votes = {
            "hist_corr": hist_corr < _HIST_CORR_MIN,
            "ssim": ssim < _SSIM_MIN,
            "hu_moments": hu_dist > _HU_DISTANCE_MAX,
        }
        suspect = sum(votes.values()) >= _SUSPECT_VOTES
        suspect_count += int(suspect)
        pairs.append(
            {
                "frame_a_ms": ts_a,
                "frame_b_ms": ts_b,
                "crop": crop_a,
                "hist_corr": round(hist_corr, 3),
                "ssim": round(ssim, 3),
                "hu_distance": round(hu_dist, 2),
                "suspect": suspect,
            },
        )
    total = len(pairs)
    return {
        "measured": True,
        "pair_count": total,
        "consistent_ratio": round((total - suspect_count) / total, 3),
        "suspect_pairs": [pair for pair in pairs if pair["suspect"]],
        "note": ("suspect 仅是程序嫌疑（同人换角度/换光也会触发），" "须结合对应时间戳画面确认后才可作为发现"),
    }


__all__ = ["cross_shot_consistency_facts"]
