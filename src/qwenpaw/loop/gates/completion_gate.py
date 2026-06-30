# -*- coding: utf-8 -*-
"""ReactCompletionGate — re-prompt on text-only turns.

Prevents premature stop when the LLM outputs text
without any tool calls.  Configurable via
``RubricGateConfig`` from agent config.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .base import StopAction, StopGate, StopHandlerResult

logger = logging.getLogger(__name__)


class ReactCompletionGate(StopGate):
    """Re-prompt the agent on text-only responses.

    The gate counts how many times it has intervened
    within the current request cycle.  Once
    ``max_interventions`` is reached it returns None
    and lets the default stop behaviour take over.
    """

    def __init__(
        self,
        prompt: str = "",
        max_interventions: int = 1,
    ) -> None:
        self._prompt = prompt
        self._max = max_interventions
        self._count = 0

    @property
    def name(self) -> str:
        return "react_completion"

    @property
    def priority(self) -> int:
        return 90

    async def check(
        self,
        ctx: Any,
    ) -> Optional[StopHandlerResult]:
        """Return CONTINUE up to max_interventions."""
        if self._count >= self._max:
            self._count = 0
            return None

        self._count += 1
        logger.debug(
            "ReactCompletionGate: intervene %d/%d",
            self._count,
            self._max,
        )
        return StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message=self._prompt,
            reason="text-only response re-prompt",
        )


__all__ = ["ReactCompletionGate"]
