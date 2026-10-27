# -*- coding: utf-8 -*-
"""Code-owned Visual Compact policy and compression presets."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping, cast

VisualCompressionEffort = Literal["low", "medium", "high"]

CANVAS_WIDTH = 1568
CANVAS_MAX_HEIGHT = 728
CANVAS_PADDING = 4
IMAGE_PATCH_SIZE = 28
IMAGE_COST_SAFETY_MARGIN = 1.10
MAX_VISUAL_COST_RATIO = 0.90
CHARS_PER_TEXT_TOKEN_FALLBACK = 4.0

FACTSHEET_MAX_ENTRIES = 96
FACTSHEET_MAX_SCAN_CHARS = 262_144
FACTSHEET_MAX_DISTINCT = 2_048
FACTSHEET_MAX_CHUNK_CHARS = 512
FACTSHEET_PAGE_CHARS = 28_080

HISTORY_KEEP_RECENT_TURNS = 2
HISTORY_BATCH_MIN_PAGES = 0.75
HISTORY_MIN_TAIL_PAGE_FILL = 0.25
MAX_IMAGES_PER_REQUEST = 64
ROLE_MARK_USER = "\x01"
ROLE_MARK_ASSISTANT = "\x02"


@dataclass(frozen=True)
class EffortPreset:
    """Values that change with the selected compression intensity."""

    effort: VisualCompressionEffort
    cell_width: int
    line_height: int
    readable_chars_per_image: int


EFFORT_PRESETS: Mapping[
    VisualCompressionEffort,
    EffortPreset,
] = MappingProxyType(
    {
        "low": EffortPreset(
            effort="low",
            cell_width=8,
            line_height=16,
            readable_chars_per_image=8_775,
        ),
        "medium": EffortPreset(
            effort="medium",
            cell_width=6,
            line_height=13,
            readable_chars_per_image=14_300,
        ),
        "high": EffortPreset(
            effort="high",
            cell_width=5,
            line_height=8,
            readable_chars_per_image=28_080,
        ),
    },
)


def effort_preset(effort: str) -> EffortPreset:
    """Return the validated preset for a persisted effort value."""
    if effort not in EFFORT_PRESETS:
        raise ValueError(f"unknown Visual Compact effort: {effort}")
    return EFFORT_PRESETS[cast(VisualCompressionEffort, effort)]


LOW_EFFORT_PRESET = EFFORT_PRESETS["low"]


__all__ = [
    "CANVAS_MAX_HEIGHT",
    "CANVAS_PADDING",
    "CANVAS_WIDTH",
    "CHARS_PER_TEXT_TOKEN_FALLBACK",
    "EFFORT_PRESETS",
    "EffortPreset",
    "FACTSHEET_MAX_CHUNK_CHARS",
    "FACTSHEET_MAX_DISTINCT",
    "FACTSHEET_MAX_ENTRIES",
    "FACTSHEET_MAX_SCAN_CHARS",
    "FACTSHEET_PAGE_CHARS",
    "HISTORY_BATCH_MIN_PAGES",
    "HISTORY_MIN_TAIL_PAGE_FILL",
    "HISTORY_KEEP_RECENT_TURNS",
    "IMAGE_COST_SAFETY_MARGIN",
    "IMAGE_PATCH_SIZE",
    "LOW_EFFORT_PRESET",
    "MAX_IMAGES_PER_REQUEST",
    "MAX_VISUAL_COST_RATIO",
    "ROLE_MARK_ASSISTANT",
    "ROLE_MARK_USER",
    "VisualCompressionEffort",
    "effort_preset",
]
