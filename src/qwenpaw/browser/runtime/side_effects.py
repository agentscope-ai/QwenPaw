# -*- coding: utf-8 -*-
"""Read, state-change, and transmission taxonomy for execution policy."""

from __future__ import annotations

from enum import Enum
from typing import Any


class SideEffectClass(Enum):
    READ = "read"
    STATE_CHANGE = "state_change"
    TRANSMIT = "transmit"


READ_ONLY_METHODS = frozenset(
    {
        "capture_tree",
        "list_pages",
        "current_surface",
        "locator_count",
        "locator_read",
        "query",
    },
)
TRANSMIT_METHODS = frozenset({"upload_file", "download", "handoff"})


def classify_side_effect(
    method: str,
    params: dict[str, Any] | None = None,
) -> SideEffectClass:
    """Classify actual provider semantics, not LLM-described intent."""
    del params
    if method in READ_ONLY_METHODS:
        return SideEffectClass.READ
    if method in TRANSMIT_METHODS:
        return SideEffectClass.TRANSMIT
    return SideEffectClass.STATE_CHANGE


def is_side_effecting(method: str) -> bool:
    """Backward-compatible state-or-transmit predicate for broker callers."""
    return classify_side_effect(method) is not SideEffectClass.READ
