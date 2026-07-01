# -*- coding: utf-8 -*-
"""Gate abstraction for the universal stop handler.

Defines the StopGate ABC, StopAction enum, and
StopHandlerResult dataclass.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


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
    """A registered stop handler with metadata.

    ``scope`` isolates handlers by mode. When a handler
    with a non-"default" scope is active, handlers with
    ``scope="default"`` are skipped so that mode-specific
    gates take precedence.
    """

    plugin_id: str
    handler: Any
    priority: int = 100
    name: str = ""
    scope: str = ""


class StopGate(ABC):
    """Abstract base class for all stop condition gates.

    Lifecycle per evaluation:
    1. check(ctx) is called
    2. If returns StopHandlerResult(STOP) -> stop
    3. If returns None -> call continuation_prompt()
       to collect additional context for the
       continuation message

    Subclasses MUST implement:
    - name (property): unique gate identifier
    - check(ctx): stop condition logic

    Subclasses MAY override:
    - priority (property): evaluation order, default 100
    - continuation_prompt(): additional text to inject
      into continuation when not stopping
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique gate identifier (for unregister)."""

    @property
    def priority(self) -> int:
        """Evaluation order. Lower = earlier."""
        return 100

    @abstractmethod
    async def check(
        self,
        ctx: Any,
    ) -> Optional[StopHandlerResult]:
        """Evaluate one stop condition.

        Returns:
            StopHandlerResult(STOP) -> agent stops.
            StopHandlerResult(CONTINUE) -> loop active.
            None -> gate idle / no opinion.
        """

    def continuation_prompt(self) -> str:
        """Additional context for the continuation msg.

        Called only after check() returns None.
        StopHandler collects all non-empty results
        and prepends them to the base continuation.
        """
        return ""


__all__ = [
    "StopAction",
    "StopGate",
    "StopHandlerRegistration",
    "StopHandlerResult",
]
