# -*- coding: utf-8 -*-
"""Doom loop detection and HITL escalation."""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class DoomLoopSignal(str, Enum):
    """Return values from a tool call observer."""

    OK = "ok"
    ESCALATE_HITL = "escalate_hitl"
    FORCE_STOP = "force_stop"


@dataclass
class ObserverRegistration:
    """A registered tool call observer with metadata."""

    plugin_id: str
    observer: Callable[..., Any]
    name: str = ""


@dataclass
class ToolCallRecord:
    """One recorded tool call for pattern analysis."""

    tool_name: str
    args_hash: str
    success: bool


class DoomLoopDetector:
    """Sliding-window detector for repetitive tool patterns.

    Compares the last ``window_size`` tool calls. If action
    similarity exceeds ``threshold``, returns ESCALATE_HITL.
    """

    def __init__(
        self,
        *,
        window_size: int = 3,
        similarity_threshold: float = 0.8,
        action: str = "hitl",
        hitl_message: str = "",
    ) -> None:
        self._window_size = max(2, window_size)
        self._threshold = similarity_threshold
        self._action = action
        self._hitl_message = hitl_message
        self._history: deque[ToolCallRecord] = deque(
            maxlen=self._window_size * 2,
        )

    @property
    def hitl_message(self) -> str:
        return self._hitl_message

    def record(
        self,
        tool_name: str,
        args_hash: str,
        success: bool,
    ) -> None:
        """Record a completed tool call."""
        self._history.append(
            ToolCallRecord(
                tool_name=tool_name,
                args_hash=args_hash,
                success=success,
            ),
        )

    def check(self) -> DoomLoopSignal:
        """Check if recent calls form a doom loop pattern."""
        if len(self._history) < self._window_size:
            return DoomLoopSignal.OK

        window = list(self._history)[-self._window_size :]
        similarity = self._compute_similarity(window)

        if similarity >= self._threshold:
            logger.warning(
                f"Doom loop detected: similarity={similarity:.2f}"
                f" threshold={self._threshold}",
            )
            if self._action == "force_stop":
                return DoomLoopSignal.FORCE_STOP
            return DoomLoopSignal.ESCALATE_HITL

        return DoomLoopSignal.OK

    @staticmethod
    def _compute_similarity(
        window: list[ToolCallRecord],
    ) -> float:
        """Compute action pattern similarity within window.

        Returns 1.0 if all calls have same name+args, 0.0 if
        all are different.
        """
        if not window:
            return 0.0

        signatures = [f"{r.tool_name}:{r.args_hash}" for r in window]
        unique = len(set(signatures))
        total = len(signatures)

        if total <= 1:
            return 0.0

        return 1.0 - (unique - 1) / (total - 1)

    def reset(self) -> None:
        """Clear history (e.g. on loop cancel)."""
        self._history.clear()


@dataclass
class DoomLoopState:
    """Per-session doom loop tracking state."""

    detector: DoomLoopDetector = field(
        default_factory=DoomLoopDetector,
    )
    paused: bool = False
    escalation_count: int = 0


__all__ = [
    "DoomLoopDetector",
    "DoomLoopSignal",
    "DoomLoopState",
    "ObserverRegistration",
    "ToolCallRecord",
]
