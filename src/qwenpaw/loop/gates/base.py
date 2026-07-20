# -*- coding: utf-8 -*-
"""Gate abstraction for the universal stop handler.

Defines the StopGate ABC, StopAction enum, and
StopHandlerResult dataclass.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional


class StopAction(str, Enum):
    """Gate decisions for the agent loop.

    BYPASS: gate has no opinion, skip.
    INTERRUPT_AND_CONTINUE: interrupt current pattern,
        inject a prompt, then keep the loop going.
    TERMINATE: end the agent loop immediately.
    """

    BYPASS = "bypass"
    INTERRUPT_AND_CONTINUE = "interrupt_and_continue"
    TERMINATE = "terminate"


@dataclass
class StopHandlerResult:
    """Return value from a stop handler / gate.

    When ``action`` is INTERRUPT_AND_CONTINUE,
    ``continuation_message`` is injected as the next
    user turn to keep the agent running.
    """

    action: StopAction = StopAction.TERMINATE
    continuation_message: str = ""
    reason: str = ""
    reset_peers: bool = False


@dataclass
class StopHandlerRegistration:
    """A registered stop handler with metadata.

    ``scope`` isolates handlers by mode. When a handler
    with a non-"default" scope is active, handlers with
    ``scope="default"`` are skipped so that mode-specific
    gates take precedence. ``is_active`` lets the owning
    mode declare scope activity without exposing gate state.
    """

    plugin_id: str
    handler: Any
    priority: int = 100
    name: str = ""
    scope: str = ""
    is_active: Callable[[], bool] | None = None


class StopGate(ABC):
    """Abstract base class for all stop condition gates.

    Lifecycle per evaluation (driven by StopHandler):
    1. check(ctx) returns action + reason + reset_peers
    2. TERMINATE -> stop immediately
    3. INTERRUPT_AND_CONTINUE -> handler calls
       build_continuation() to get the message,
       then injects it as a new user turn
    4. BYPASS / None -> gate idle, no action

    Subclasses MUST implement:
    - name (property): unique gate identifier
    - check(ctx): stop condition logic

    Subclasses MAY override:
    - priority (property): evaluation order, default 100
    - build_continuation(): text to inject when
      INTERRUPT_AND_CONTINUE is triggered
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
            TERMINATE -> agent stops.
            INTERRUPT_AND_CONTINUE -> handler calls
                build_continuation() for the message.
            BYPASS or None -> gate idle / no opinion.
        """

    def build_continuation(self) -> str:
        """Return the text to inject as a user turn.

        Called by StopHandler when check() returns
        INTERRUPT_AND_CONTINUE. Subclasses override
        to provide gate-specific continuation prompts.
        """
        return ""

    def reset_turn(self) -> None:
        """Reset state for the current turn.

        Stateful gates override this to clear internal
        counters/history. Default implementation is a no-op
        for stateless gates.
        """

    def reset_session(self) -> None:
        """Remove state for the current conversation session."""


__all__ = [
    "StopAction",
    "StopGate",
    "StopHandlerRegistration",
    "StopHandlerResult",
]
