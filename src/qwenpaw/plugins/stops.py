# -*- coding: utf-8 -*-
"""Mode advice at the host-owned stop decision; never resets host budgets."""

from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

from .context import RequestContext
from .messages import Message
from .tools import ToolContext


@dataclass(frozen=True)
class StopContext(ToolContext):
    """Advice after a reasoning turn; iteration counts completed turns from 1."""

    iteration: int = 0
    has_tool_calls: bool = False
    final_message: Message | None = None


@dataclass(frozen=True)
class StopResult:
    action: Literal["bypass", "continue", "stop"] = "bypass"
    message: str = ""
    reason: str = ""


@dataclass(frozen=True)
class StopSpec:
    name: str
    handler: Callable[[StopContext], StopResult | Awaitable[StopResult]]
    is_active: Callable[[RequestContext], bool]
    priority: int = 100
    timeout: float = 30.0
