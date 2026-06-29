# -*- coding: utf-8 -*-
"""Agent stop handler — blocks agent exit when loop is active."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class StopAction(str, Enum):
    """Whether to allow or block agent from stopping."""

    ALLOW = "allow"
    BLOCK = "block"


@dataclass
class StopHandlerResult:
    """Return value from a stop handler.

    When ``action`` is BLOCK, ``continuation_message`` is injected
    as the next user turn to keep the agent running.
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


__all__ = [
    "StopAction",
    "StopHandlerRegistration",
    "StopHandlerResult",
]
