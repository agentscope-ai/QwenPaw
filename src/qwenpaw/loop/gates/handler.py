# -*- coding: utf-8 -*-
"""Universal StopHandler with composable gates.

Architecture:
    StopHandler holds an ordered list of StopGate.
    Gates are checked in priority order (lower first).
    TERMINATE -> agent stops immediately.
    INTERRUPT_AND_CONTINUE -> call gate.build_continuation()
        to get the message, then inject it.
    BYPASS / None -> skip.
    No gates or all BYPASS -> TERMINATE.
"""
from __future__ import annotations

import logging
from typing import Any

from .base import (
    StopAction,
    StopGate,
    StopHandlerResult,
)

logger = logging.getLogger(__name__)


class StopHandler:
    """Universal stop handler with composable gates.

    TERMINATE -> agent stops immediately.
    INTERRUPT_AND_CONTINUE -> inject prompt via
        gate.build_continuation(), keep going.
    BYPASS / None -> skip.
    No gates or all BYPASS -> TERMINATE.
    """

    def __init__(self) -> None:
        self._gates: list[StopGate] = []

    def register(self, gate: StopGate) -> None:
        """Register a gate and re-sort by priority."""
        self._gates.append(gate)
        self._gates.sort(key=lambda g: g.priority)

    def unregister(self, name: str) -> None:
        """Remove all gates matching *name*."""
        self._gates = [g for g in self._gates if g.name != name]

    @property
    def gates(self) -> list[StopGate]:
        """Read-only view of registered gates."""
        return list(self._gates)

    def reset(self) -> None:
        """Reset stateful gates without unregistering them."""
        for gate in self._gates:
            reset = getattr(gate, "reset", None)
            if callable(reset):
                try:
                    reset()
                except Exception:
                    logger.warning(
                        "StopGate '%s' reset raised",
                        gate.name,
                        exc_info=True,
                    )

    async def __call__(
        self,
        ctx: Any,
    ) -> StopHandlerResult:
        """Run all gates in priority order.

        TERMINATE -> stop immediately.
        INTERRUPT_AND_CONTINUE -> inject prompt, keep going.
        BYPASS / None -> gate idle, skip.
        No gates or all BYPASS -> TERMINATE.
        """
        if not self._gates:
            return StopHandlerResult(
                action=StopAction.TERMINATE,
            )

        has_continue = False
        continue_result: StopHandlerResult | None = None
        continue_gate: StopGate | None = None

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

            if result is None or (result.action == StopAction.BYPASS):
                continue

            logger.debug(
                "StopGate '%s' fired: %s",
                gate.name,
                result.action.value,
            )
            if result.action == StopAction.TERMINATE:
                return result
            has_continue = True
            if continue_result is None:
                continue_result = result
                continue_gate = gate

        if not has_continue:
            return StopHandlerResult(
                action=StopAction.TERMINATE,
            )

        self._maybe_reset_peers(
            continue_result,
            continue_gate,
        )

        msg = continue_gate.build_continuation() if continue_gate else ""
        return StopHandlerResult(
            action=StopAction.INTERRUPT_AND_CONTINUE,
            continuation_message=msg,
            reason=(
                continue_result.reason
                if continue_result
                else "Active gate continues"
            ),
        )

    def _maybe_reset_peers(
        self,
        continue_result: StopHandlerResult | None,
        continue_gate: StopGate | None,
    ) -> None:
        """Reset peer gates on sub-turn continuation.

        IMPORTANT: When a gate triggers
        INTERRUPT_AND_CONTINUE with reset_peers=True (e.g. rubric gate starting
        a new sub-turn), reset all OTHER gates so they
        begin the sub-turn with fresh state (iteration
        counter, doom loop history, etc.).
        Gates that merely inject warnings (e.g. doom
        loop modify_prompt) keep reset_peers=False and
        do NOT trigger peer resets.
        """
        if continue_result is None or not continue_result.reset_peers:
            return
        for gate in self._gates:
            if gate is not continue_gate:
                gate.reset()


__all__ = ["StopHandler"]
