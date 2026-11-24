# -*- coding: utf-8 -*-
"""Runtime hooks expose message snapshots and explicit permitted changes."""

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Literal, Awaitable

from .messages import Message
from .tools import ToolContext


class HookPhase(str, Enum):
    PRE_DISPATCH = "pre_dispatch"
    POST_DISPATCH = "post_dispatch"
    PRE_AGENT_BUILD = "pre_agent_build"
    POST_AGENT_BUILD = "post_agent_build"
    PRE_EXECUTE = "pre_execute"
    POST_RESPONSE = "post_response"
    ON_ERROR = "on_error"
    FINALLY = "finally"


@dataclass(frozen=True)
class ContextInjection:
    content: str
    priority: int = 100


@dataclass(frozen=True)
class HookContext(ToolContext):
    phase: HookPhase = HookPhase.PRE_DISPATCH
    messages: tuple[Message, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class HookResult:
    action: Literal["continue", "reply", "skip_agent"] = "continue"
    message: Message | None = None
    replace_input: tuple[Message, ...] | None = None
    injections: tuple[ContextInjection, ...] = ()


@dataclass(frozen=True)
class HookSpec:
    name: str
    phase: HookPhase
    handler: Callable[[HookContext], HookResult | Awaitable[HookResult]]
    priority: int = 100
    before: tuple[str, ...] = ()
    after: tuple[str, ...] = ()
    timeout: float | None = 30.0
