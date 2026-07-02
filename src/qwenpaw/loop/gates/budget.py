# -*- coding: utf-8 -*-
"""BudgetGate — universal token budget limiter.

Tracks per-session token usage. Returns STOP when
``max_tokens`` is exceeded.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from .base import StopAction, StopHandlerResult
from .loop_gate import LoopGate

logger = logging.getLogger(__name__)


@dataclass
class _BudgetState:
    """Per-session token budget state."""

    tokens_used: int = 0
    max_tokens: int = 300_000


class BudgetGate(LoopGate):
    """Hard token budget cap.  Priority 20."""

    def __init__(
        self,
        max_tokens: int = 300_000,
    ) -> None:
        super().__init__()
        self._default_max = max_tokens

    @property
    def name(self) -> str:
        return "budget"

    @property
    def priority(self) -> int:
        return 20

    def activate(  # pylint: disable=arguments-renamed
        self,
        max_tokens: int | None = None,
    ) -> None:
        """Activate with optional custom budget."""
        limit = max_tokens or self._default_max
        super().activate(
            _BudgetState(max_tokens=limit),
        )

    def update_tokens(self, tokens: int) -> None:
        """Update token usage for current session."""
        state: Optional[_BudgetState] = self._state()
        if state is not None:
            state.tokens_used = tokens

    async def check(
        self,
        ctx: Any,  # pylint: disable=unused-argument
    ) -> Optional[StopHandlerResult]:
        """Check token budget."""
        state: Optional[_BudgetState] = self._state()
        if state is None:
            return None

        if state.tokens_used >= state.max_tokens:
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.STOP,
                reason="Token budget exceeded",
            )
        return None


__all__ = ["BudgetGate"]
