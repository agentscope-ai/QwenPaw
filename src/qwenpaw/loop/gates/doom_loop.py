# -*- coding: utf-8 -*-
"""DoomLoopGate: self-contained multi-stage doom loop gate.

Includes inline sliding-window similarity detection.
No external dependencies on legacy loop files.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

from .base import (
    StopAction,
    StopGate,
    StopHandlerResult,
)

logger = logging.getLogger(__name__)


@dataclass
class _ToolCallRecord:
    """One recorded tool call for pattern analysis."""

    tool_name: str
    args_hash: str


class DoomLoopGate(StopGate):
    """Multi-stage doom loop gate for StopHandler.

    Self-contained: includes sliding-window repetition
    detection. Escalates through configured stages.
    Each stage triggers after N consecutive repetitions.

    - action="modify_prompt": inject warning via
      continuation_prompt(), don't stop.
    - action="stop": return STOP immediately.
    """

    @property
    def name(self) -> str:
        return "doom-loop"

    @property
    def priority(self) -> int:
        return 5

    def __init__(
        self,
        *,
        window_size: int = 5,
        similarity_threshold: float = 0.8,
        stages: list | None = None,
    ) -> None:
        self._window_size = max(2, window_size)
        self._threshold = similarity_threshold
        self._stages = sorted(
            stages or [],
            key=lambda s: s.after,
        )
        self._history: deque[_ToolCallRecord] = deque(
            maxlen=self._window_size * 2,
        )
        self._consecutive_hits: int = 0
        self._prompt: str = ""

    # ---- Public: record tool calls ----

    def record(
        self,
        tool_name: str,
        args_hash: str,
    ) -> None:
        """Record a completed tool call."""
        self._history.append(
            _ToolCallRecord(
                tool_name=tool_name,
                args_hash=args_hash,
            ),
        )

    def reset(self) -> None:
        """Clear history and state."""
        self._history.clear()
        self._consecutive_hits = 0
        self._prompt = ""

    # ---- StopGate interface ----

    async def check(
        self,
        ctx: Any,  # pylint: disable=unused-argument
    ) -> Optional[StopHandlerResult]:
        """Evaluate doom loop state."""
        is_looping = self._detect_repetition()

        if not is_looping:
            self._consecutive_hits = 0
            self._prompt = ""
            return None

        self._consecutive_hits += 1

        active_stage = None
        for stage in reversed(self._stages):
            if self._consecutive_hits >= stage.after:
                active_stage = stage
                break

        if active_stage is None:
            return None

        if active_stage.action == "stop":
            logger.info(
                "DoomLoopGate: STOP after %d hits",
                self._consecutive_hits,
            )
            return StopHandlerResult(
                action=StopAction.STOP,
                reason=active_stage.prompt,
            )

        self._prompt = active_stage.prompt
        logger.debug(
            "DoomLoopGate: warning at %d hits",
            self._consecutive_hits,
        )
        return None

    def continuation_prompt(self) -> str:
        """Return current doom loop warning."""
        return self._prompt

    # ---- Internal detection ----

    def _detect_repetition(self) -> bool:
        """Check sliding window for repetitive pattern."""
        if len(self._history) < self._window_size:
            return False

        window = list(self._history)[-self._window_size :]
        similarity = self._compute_similarity(window)

        if similarity >= self._threshold:
            logger.warning(
                "Doom loop: sim=%.2f thr=%.2f",
                similarity,
                self._threshold,
            )
            return True
        return False

    @staticmethod
    def _compute_similarity(
        window: list[_ToolCallRecord],
    ) -> float:
        """Compute action pattern similarity.

        Formula: 1 - (unique - 1) / (total - 1)
        """
        if not window or len(window) <= 1:
            return 0.0

        sigs = [f"{r.tool_name}:{r.args_hash}" for r in window]
        unique = len(set(sigs))
        total = len(sigs)
        return 1.0 - (unique - 1) / (total - 1)


__all__ = ["DoomLoopGate"]
