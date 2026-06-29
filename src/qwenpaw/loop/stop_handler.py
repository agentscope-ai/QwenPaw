# -*- coding: utf-8 -*-
"""Universal stop handler with composable gates.

Architecture:
    StopHandler holds an ordered list of StopGate.
    Gates are checked in priority order (lower first).
    First gate returning a result wins.
    Default when no gate fires: ALLOW (agent stops).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class StopAction(str, Enum):
    """Whether to allow or block agent from stopping."""

    ALLOW = "allow"
    BLOCK = "block"


@dataclass
class StopHandlerResult:
    """Return value from a stop handler / gate.

    When ``action`` is BLOCK, ``continuation_message``
    is injected as the next user turn to keep the
    agent running.
    """

    action: StopAction = StopAction.ALLOW
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

    Each gate checks one condition and returns:
    - StopHandlerResult → terminate gate evaluation
    - None → pass to next gate
    """

    name: str = ""
    priority: int = 100

    @abstractmethod
    async def check(
        self,
        ctx: Any,
    ) -> Optional[StopHandlerResult]:
        """Check stop condition.

        Returns:
            StopHandlerResult to stop evaluation,
            None to pass to the next gate.
        """


class StopHandler:
    """Universal stop handler with composable gates.

    Gates are checked in priority order (lower first).
    First gate that returns a non-None result wins.
    If no gate fires, returns ALLOW (agent stops).
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

    async def __call__(
        self,
        ctx: Any,
    ) -> StopHandlerResult:
        """Run all gates in priority order."""
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
        return StopHandlerResult(
            action=StopAction.ALLOW,
        )


__all__ = [
    "StopAction",
    "StopGate",
    "StopHandler",
    "StopHandlerRegistration",
    "StopHandlerResult",
]
