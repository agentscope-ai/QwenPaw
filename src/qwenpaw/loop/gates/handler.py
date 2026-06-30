# -*- coding: utf-8 -*-
"""Universal StopHandler with composable gates.

Architecture:
    StopHandler holds an ordered list of StopGate.
    Gates are checked in priority order (lower first).
    Any gate returning STOP -> agent stops immediately.
    Any gate returning CONTINUE -> loop keeps going.
    No gates registered OR all None -> STOP.
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
    Any gate returning CONTINUE -> loop keeps going.
    No gates registered OR all None -> STOP.
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

        Any STOP  -> stop immediately.
        Any CONTINUE -> loop keeps going.
        All None / no gates -> STOP (no active loop).
        """
        if not self._gates:
            return StopHandlerResult(
                action=StopAction.STOP,
            )

        prompts: list[str] = []
        has_continue = False
        continue_result: StopHandlerResult | None = None

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
                if result.action == StopAction.STOP:
                    return result
                has_continue = True
                if continue_result is None:
                    continue_result = result

            prompt = gate.continuation_prompt()
            if prompt:
                prompts.append(prompt)

        if not has_continue:
            return StopHandlerResult(
                action=StopAction.STOP,
            )

        msg = continue_result.continuation_message if continue_result else ""
        if self._continuation_fn:
            try:
                fn_msg = self._continuation_fn(ctx)
            except Exception:
                logger.warning(
                    "continuation_fn raised",
                    exc_info=True,
                )
                fn_msg = ""
            if fn_msg:
                msg = f"{msg}\n\n{fn_msg}" if msg else fn_msg
        if prompts:
            prefix = "\n\n".join(prompts)
            msg = f"{prefix}\n\n{msg}" if msg else prefix
        return StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message=msg,
            reason=(
                continue_result.reason
                if continue_result
                else "Active gate continues"
            ),
        )


__all__ = ["StopHandler"]
