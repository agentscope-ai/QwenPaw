# -*- coding: utf-8 -*-
"""Learning signal accumulator for detecting skill-worthy patterns.

Tracks weighted signals during agent execution: tool calls,
error recoveries, and user corrections.  The weighted score
determines when a background skill review is triggered.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...config.config import SignalWeightsConfig

# Patterns that indicate a user correction (zh + en).
# Applied to user messages only; no LLM call required.
_CORRECTION_PATTERNS = re.compile(
    r"不对|不是|错了|换个|别用|不要这样|重新|改一下"
    r"|wrong|no[,.\s]|don'?t|instead|actually|try .+ instead"
    r"|应该|要用|改成|should\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LearningSignals:
    """Immutable snapshot of accumulated learning signals."""

    tool_calls: int = 0
    error_recoveries: int = 0
    user_corrections: int = 0

    def weighted_score(self, weights: "SignalWeightsConfig") -> int:
        """Compute weighted score from signal counts."""
        return (
            self.tool_calls * weights.tool_call
            + self.error_recoveries * weights.error_recovery
            + self.user_corrections * weights.user_correction
        )


@dataclass
class _PreviousIterState:
    """Mutable scratch space for error-recovery detection."""

    had_error: bool = False
    tool_names: list[str] = field(default_factory=list)


class LearningSignalAccumulator:
    """Accumulates learning signals during a single agent turn."""

    def __init__(self) -> None:
        self._tool_calls: int = 0
        self._error_recoveries: int = 0
        self._user_corrections: int = 0
        self._prev = _PreviousIterState()

    # -- recording helpers --

    def record_tool_calls(
        self,
        count: int,
        *,
        tool_names: list[str] | None = None,
        any_error: bool = False,
    ) -> None:
        """Record tool-call iteration results.

        Args:
            count: Number of tool calls in this iteration.
            tool_names: Names of the tools called.
            any_error: Whether any tool returned an error.
        """
        self._tool_calls += count

        names = tool_names or []
        if (
            self._prev.had_error
            and names
            and set(names) != set(self._prev.tool_names)
        ):
            self._error_recoveries += 1

        self._prev = _PreviousIterState(
            had_error=any_error,
            tool_names=list(names),
        )

    def record_user_correction(self) -> None:
        self._user_corrections += 1

    # -- static detection helper --

    @staticmethod
    def is_user_correction(text: str) -> bool:
        """Return True if *text* looks like a user correction."""
        if not text:
            return False
        return bool(_CORRECTION_PATTERNS.search(text))

    # -- snapshot / reset --

    def snapshot(self) -> LearningSignals:
        return LearningSignals(
            tool_calls=self._tool_calls,
            error_recoveries=self._error_recoveries,
            user_corrections=self._user_corrections,
        )

    def reset(self) -> None:
        self._tool_calls = 0
        self._error_recoveries = 0
        self._user_corrections = 0
        self._prev = _PreviousIterState()
