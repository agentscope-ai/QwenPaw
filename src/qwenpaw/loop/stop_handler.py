# -*- coding: utf-8 -*-
"""Universal stop handler with composable gates.

Architecture:
    StopHandler holds an ordered list of StopGate.
    Gates are checked in priority order (lower first).
    Any gate returning STOP → agent stops immediately.
    No gates registered → STOP (normal non-loop exit).
    All gates return None → CONTINUE (loop keeps going).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class StopAction(str, Enum):
    """Whether the agent should stop or continue."""

    STOP = "stop"
    CONTINUE = "continue"

    # Backward-compatible aliases
    ALLOW = "stop"
    BLOCK = "continue"


@dataclass
class StopHandlerResult:
    """Return value from a stop handler / gate.

    When ``action`` is CONTINUE, ``continuation_message``
    is injected as the next user turn to keep the
    agent running.
    """

    action: StopAction = StopAction.STOP
    continuation_message: str = ""
    reason: str = ""


@dataclass
class StopHandlerRegistration:
    """A registered stop handler with metadata."""

    plugin_id: str
    handler: Callable[..., Any]
    priority: int = 100
    name: str = ""


# ---- Gate abstraction ----


class StopGate(ABC):
    """Base class for stop condition gates.

    Return StopHandlerResult(STOP) to stop the agent.
    Return None to pass (no objection, next gate).
    Optionally override get_warning() to inject
    warnings into the continuation prompt without
    triggering a stop.
    """

    name: str = ""
    priority: int = 100

    @abstractmethod
    async def check(
        self,
        ctx: Any,
    ) -> Optional[StopHandlerResult]:
        """Evaluate one stop condition.

        Returns:
            StopHandlerResult(STOP) -> agent stops.
            None -> no objection, check next gate.
        """

    def get_warning(self) -> str:
        """Optional warning to prepend to continuation.

        Called after check() returns None. StopHandler
        collects all warnings and prepends them to the
        continuation message.
        """
        return ""


class StopHandler:
    """Universal stop handler with composable gates.

    Any gate returning STOP → agent stops immediately.
    No gates registered → STOP (normal non-loop exit).
    All gates return None → CONTINUE with the
    continuation message from ``continuation_fn``.
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
        All None -> continue (with collected warnings).
        """
        if not self._gates:
            return StopHandlerResult(
                action=StopAction.STOP,
            )

        warnings: list[str] = []
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
            warning = gate.get_warning()
            if warning:
                warnings.append(warning)

        msg = ""
        if self._continuation_fn:
            try:
                msg = self._continuation_fn(ctx)
            except Exception:
                logger.warning(
                    "continuation_fn raised",
                    exc_info=True,
                )
        if warnings:
            msg = "\n\n".join(warnings) + "\n\n" + msg
        return StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message=msg,
            reason="All gates passed",
        )


__all__ = [
    "StopAction",
    "StopGate",
    "StopHandler",
    "StopHandlerRegistration",
    "StopHandlerResult",
]
