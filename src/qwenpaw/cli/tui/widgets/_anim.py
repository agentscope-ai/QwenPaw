# -*- coding: utf-8 -*-
"""Tiny animation helpers shared by live widgets (thinking lane, running
tool panels): a braille spinner and a pulsing blue→purple colour cycle.

Frame-indexed so callers just keep a counter and tick it on a timer."""

from __future__ import annotations

# Braille spinner frames (smooth, monospace-friendly).
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Blue→purple shimmer; bounces so the pulse feels continuous.
_PULSE = (
    "#6db8ff",
    "#7fa6ff",
    "#9c8cff",
    "#b48cff",
    "#9c8cff",
    "#7fa6ff",
)

# Recommended timer interval (seconds) for ticking the frame counter.
TICK = 0.1


def spinner(frame: int) -> str:
    """Spinner glyph for *frame*."""
    return _SPINNER[frame % len(_SPINNER)]


def pulse(frame: int) -> str:
    """Pulsing colour (hex) for *frame*."""
    return _PULSE[frame % len(_PULSE)]
