# -*- coding: utf-8 -*-
"""DoomLoopGate: multi-stage doom loop stop gate."""
from __future__ import annotations

import logging
from typing import Any, Optional

from .base import (
    StopAction,
    StopGate,
    StopHandlerResult,
)

logger = logging.getLogger(__name__)


class DoomLoopGate(StopGate):
    """Multi-stage doom loop gate for StopHandler.

    Checks DoomLoopDetector signal and escalates
    through configured stages. Each stage triggers
    after N consecutive repetitions.

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
        detector: Any,
        stages: list | None = None,
    ) -> None:
        self._detector = detector
        self._stages = sorted(
            stages or [],
            key=lambda s: s.after,
        )
        self._consecutive_hits: int = 0
        self._prompt: str = ""

    async def check(
        self,
        ctx: Any,  # pylint: disable=unused-argument
    ) -> Optional[StopHandlerResult]:
        """Evaluate doom loop state."""
        from ..doom_loop import DoomLoopSignal

        signal = self._detector.check()

        if signal == DoomLoopSignal.OK:
            self._consecutive_hits = 0
            self._prompt = ""
            return None

        self._consecutive_hits += 1

        if signal == DoomLoopSignal.FORCE_STOP:
            return StopHandlerResult(
                action=StopAction.STOP,
                reason="Doom loop: force stop",
            )

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


__all__ = ["DoomLoopGate"]
