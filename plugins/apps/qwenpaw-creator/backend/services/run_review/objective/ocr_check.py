# -*- coding: utf-8 -*-
"""OCR text-render verification with the APE gray-zone rule (optional).

Ported from APE-benchmark ``grader/objective/text_metrics.py``: the OCR
transcription of a frame is matched against the text the plan intended
to render via edit-distance similarity. ``best_ratio >= 0.7`` trusts the
OCR read as rendered-correctly; ``< 0.3`` reports "suspected missing or
garbled"; the ``[0.3, 0.7)`` gray zone deliberately reaches NO verdict —
the frame may be correct-but-blurry (OCR misread) or truly unrendered
(OCR guessed a similar glyph) — and is handed to the VLM for a zoomed-in
recheck instead.

OCR never judges directly: a graphic logo an OCR cannot read is not a
missing text. Everything below the trust threshold is only ever a
"suspicion" fact with the frame reference attached. Requires ``easyocr``
(optional); when absent the whole operator reports skipped and text
verification falls back to the pure-VLM path.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from threading import Lock
from typing import Any

import numpy as np

from utils.logger import setup_logger

try:  # pragma: no cover - environment-dependent optional dependency
    import easyocr  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    easyocr = None

logger = setup_logger("creator.run_review.objective.ocr")

# APE text_metrics.py gray-zone thresholds.
GRAY_ZONE_HIGH = 0.7
GRAY_ZONE_LOW = 0.3

_READER = None
_READER_LOCK = Lock()


def ocr_available() -> bool:
    return easyocr is not None


def _reader():  # pragma: no cover - requires easyocr install
    global _READER  # pylint: disable=global-statement
    if _READER is None:
        with _READER_LOCK:
            if _READER is None:
                _READER = easyocr.Reader(
                    ["ch_sim", "en"],
                    gpu=False,
                    verbose=False,
                )
    return _READER


def _similarity(expected: str, recognized: str) -> float:
    normalize = str.maketrans("", "", " \t\n\r，。,.!？?、；;：:")
    left = expected.translate(normalize).casefold()
    right = recognized.translate(normalize).casefold()
    if not left:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def text_render_facts(
    frames: list[tuple[int, np.ndarray]],
    expected_texts: list[str],
) -> dict[str, Any]:
    """Match planned overlay texts against OCR reads of sampled frames.

    ``frames`` are ``(timestamp_ms, rgb_or_gray_array)`` pairs. For each
    expected text the best similarity across all frames decides the
    bucket: trusted / gray zone (VLM recheck) / suspected missing.
    """
    if not expected_texts:
        return {"measured": False, "note": "计划未声明需渲染的文字"}
    if easyocr is None:
        return {
            "measured": False,
            "status": "skipped",
            "skip_reason": "easyocr 未安装：文字核验回退纯 VLM 路径",
        }
    reads: list[tuple[int, str]] = []
    for timestamp_ms, frame in frames:
        try:
            lines = _reader().readtext(frame, detail=0)
        except Exception:  # pragma: no cover - engine-level failure
            logger.exception("OCR read failed at %sms", timestamp_ms)
            continue
        reads.append((timestamp_ms, " ".join(str(line) for line in lines)))
    if not reads:
        return {
            "measured": False,
            "status": "skipped",
            "skip_reason": "OCR 未能读取任何帧",
        }
    trusted: list[dict[str, Any]] = []
    gray_zone: list[dict[str, Any]] = []
    suspected: list[dict[str, Any]] = []
    for expected in expected_texts:
        best_ratio = 0.0
        best_ts = reads[0][0]
        for timestamp_ms, recognized in reads:
            ratio = _similarity(expected, recognized)
            if ratio > best_ratio:
                best_ratio, best_ts = ratio, timestamp_ms
        entry = {
            "expected": expected[:80],
            "best_ratio": round(best_ratio, 3),
            "best_frame_ms": best_ts,
        }
        if best_ratio >= GRAY_ZONE_HIGH:
            trusted.append(entry)
        elif best_ratio >= GRAY_ZONE_LOW:
            gray_zone.append(entry)
        else:
            suspected.append(entry)
    return {
        "measured": True,
        "trusted": trusted,
        "gray_zone_for_vlm_recheck": gray_zone,
        "suspected_missing_or_garbled": suspected,
        "note": ("suspected 仅是嫌疑（图形化 Logo 读不出≠语义缺失）；" "灰区必须由 VLM 放大复核后才可下结论"),
    }


__all__ = [
    "GRAY_ZONE_HIGH",
    "GRAY_ZONE_LOW",
    "ocr_available",
    "text_render_facts",
]
