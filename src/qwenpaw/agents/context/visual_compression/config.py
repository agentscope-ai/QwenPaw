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

MAX_IMAGES_PER_REQUEST = 64
MAX_IMAGES_PER_TOOL_RESULT = 10
HISTORY_MIN_COLLAPSE_MESSAGES = 10
HISTORY_COLLAPSE_GRID_MESSAGES = 50
HISTORY_FREEZE_GRID_MESSAGES = 10
ROLE_MARK_USER = "\x01"
ROLE_MARK_ASSISTANT = "\x02"


@dataclass(frozen=True)
class EffortPreset:
    """Values that change with the selected compression intensity."""

    effort: VisualCompressionEffort
    cell_width: int
    line_height: int
    readable_chars_per_image: int
    static_min_chars: int
    tool_result_min_chars: int
    history_keep_recent_messages: int


EFFORT_PRESETS: Mapping[
    VisualCompressionEffort,
    EffortPreset,
] = MappingProxyType(
    {
        "low": EffortPreset(
            effort="low",
            cell_width=5,
            line_height=8,
            readable_chars_per_image=28_080,
            static_min_chars=2_000,
            tool_result_min_chars=6_000,
            history_keep_recent_messages=6,
        ),
        "medium": EffortPreset(
            effort="medium",
            cell_width=4,
            line_height=8,
            readable_chars_per_image=35_100,
            static_min_chars=1_800,
            tool_result_min_chars=5_000,
            history_keep_recent_messages=5,
        ),
        "high": EffortPreset(
            effort="high",
            cell_width=3,
            line_height=7,
            readable_chars_per_image=53_040,
            static_min_chars=1_500,
            tool_result_min_chars=4_000,
            history_keep_recent_messages=4,
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
    "HISTORY_COLLAPSE_GRID_MESSAGES",
    "HISTORY_FREEZE_GRID_MESSAGES",
    "HISTORY_MIN_COLLAPSE_MESSAGES",
    "IMAGE_COST_SAFETY_MARGIN",
    "IMAGE_PATCH_SIZE",
    "LOW_EFFORT_PRESET",
    "MAX_IMAGES_PER_REQUEST",
    "MAX_IMAGES_PER_TOOL_RESULT",
    "MAX_VISUAL_COST_RATIO",
    "ROLE_MARK_ASSISTANT",
    "ROLE_MARK_USER",
    "VisualCompressionEffort",
    "effort_preset",
]
