# -*- coding: utf-8 -*-
"""Machine-parameter facts: duration / aspect ratio / resolution.

Ported from APE-benchmark ``grader/objective/program.py``
(``duration_match`` / ``aspect_ratio`` / ``resolution_match``): duration
scores 1.0 within a ±10% deviation and decays linearly to 0 at 50%;
aspect deviation is penalized fivefold (20% off -> 0) because a wrong
aspect is normally a configuration-level hard error.

These operators only ever COMPARE against constraints the plan actually
declared; without a declared constraint they report the measurement and
nothing else. Even a declared mismatch stays an advisory fact — the
reviewer folds it into the engineering-row reasoning.
"""

from __future__ import annotations

from typing import Any, Mapping

_DURATION_FULL_DEVIATION = 0.10
_DURATION_ZERO_DEVIATION = 0.50
_ASPECT_PENALTY_FACTOR = 5.0


def _duration_score(deviation: float) -> float:
    if deviation <= _DURATION_FULL_DEVIATION:
        return 1.0
    if deviation >= _DURATION_ZERO_DEVIATION:
        return 0.0
    span = _DURATION_ZERO_DEVIATION - _DURATION_FULL_DEVIATION
    return round(1.0 - (deviation - _DURATION_FULL_DEVIATION) / span, 3)


def _parse_aspect(value: Any) -> float | None:
    """Accept ``16:9`` / ``9x16`` / plain float forms."""
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    text = str(value or "").strip().replace("x", ":").replace("X", ":")
    if ":" in text:
        left, _, right = text.partition(":")
        try:
            width, height = float(left), float(right)
        except ValueError:
            return None
        if width > 0 and height > 0:
            return width / height
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def machine_param_facts(
    info: Mapping[str, Any],
    *,
    expected_duration_seconds: float | None = None,
    expected_aspect: Any = None,
) -> dict[str, Any]:
    """Measured container facts plus declared-constraint comparisons."""
    width = int(info.get("width") or 0)
    height = int(info.get("height") or 0)
    duration = float(info.get("duration") or 0.0)
    facts: dict[str, Any] = {
        "measured": {
            "duration_seconds": round(duration, 2),
            "width": width,
            "height": height,
            "aspect": round(width / height, 4) if width and height else None,
        },
    }
    if expected_duration_seconds and expected_duration_seconds > 0:
        deviation = (
            abs(duration - expected_duration_seconds)
            / expected_duration_seconds
        )
        facts["duration_check"] = {
            "declared_seconds": round(expected_duration_seconds, 2),
            "deviation_ratio": round(deviation, 3),
            "tier_score": _duration_score(deviation),
        }
    else:
        facts["duration_check"] = {"declared": False}
    expected_ratio = _parse_aspect(expected_aspect)
    if expected_ratio and width and height:
        actual_ratio = width / height
        deviation = abs(actual_ratio - expected_ratio) / expected_ratio
        facts["aspect_check"] = {
            "declared_aspect": round(expected_ratio, 4),
            "deviation_ratio": round(deviation, 3),
            "tier_score": round(
                max(0.0, 1.0 - deviation * _ASPECT_PENALTY_FACTOR),
                3,
            ),
        }
    else:
        facts["aspect_check"] = {"declared": False}
    return facts


__all__ = ["machine_param_facts"]
