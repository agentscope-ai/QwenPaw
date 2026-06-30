# -*- coding: utf-8 -*-
"""Universal StopHandler with composable gates.

Architecture:
    StopHandler holds an ordered list of StopGate.
    Gates are checked in priority order (lower first).
    Any gate returning STOP -> agent stops immediately.
    No gates registered -> STOP (normal non-loop exit).
    All gates return None -> CONTINUE (loop keeps going).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from .base import (
    StopAction,
    StopGate,
    StopHandlerResult,
)

logger = logging.getLogger(__name__)


class StopHandler:
    """Universal stop handler with composable gates.

    Any gate returning STOP -> agent stops immediately.
    No gates registered -> STOP (normal non-loop exit).
    All gates return None -> CONTINUE with the
    continuation message from ``continuation_fn``
    plus all gate continuation_prompt() contributions.
    """

    def __init__(self) -> None:
        self._gates: list[StopGate] = []
        self._continuation_fn: (Optional[Callable[..., str]]) = None

    def register(self, gate: StopGate) -> None:
        """Register a gate and re-sort by priority."""
        self._gates.append(gate)
        self._gates.sort(key=lambda g: g.priority)

    def unregister(self, name: str) -> None:
        """Remove all gates matching *name*."""
        self._gates = [g for g in self._gates if g.name != name]

    def set_continuation(
        self,
        fn: Callable[..., str],
    ) -> None:
        """Set callback that builds continuation msg."""
        self._continuation_fn = fn

    @property
    def gates(self) -> list[StopGate]:
        """Read-only view of registered gates."""
        return list(self._gates)

    async def __call__(
        self,
        ctx: Any,
    ) -> StopHandlerResult:
        """Run all gates in priority order.

        Any STOP -> stop. No gates -> stop.
        All None -> continue (with collected prompts).
        """
        if not self._gates:
            return StopHandlerResult(
                action=StopAction.STOP,
            )

        prompts: list[str] = []
        for gate in self._gates:
            try:
                result = await gate.check(ctx)
            except Exception:
                logger.warning(
                    "StopGate '%s' raised, skipping",
                    gate.name,
                    exc_info=True,
                )
                continue
            if result is not None:
                logger.debug(
                    "StopGate '%s' fired: %s",
                    gate.name,
                    result.action.value,
                )
                return result
            prompt = gate.continuation_prompt()
            if prompt:
                prompts.append(prompt)

        msg = ""
        if self._continuation_fn:
            try:
                msg = self._continuation_fn(ctx)
            except Exception:
                logger.warning(
                    "continuation_fn raised",
                    exc_info=True,
                )
        if prompts:
            msg = "\n\n".join(prompts) + "\n\n" + msg
        return StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message=msg,
            reason="All gates passed",
        )


__all__ = ["StopHandler"]
