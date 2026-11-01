# -*- coding: utf-8 -*-
"""Mode bundles selected from an immutable request snapshot."""

from dataclasses import dataclass
from typing import Awaitable, Callable

from .commands import CommandSpec
from .hooks import HookSpec
from .messages import Message
from .prompts import PromptSpec
from .storage import PluginConfig
from .tools import ToolSpec


@dataclass(frozen=True)
class ModeContext:
    plugin_id: str
    generation: int
    workspace_id: str
    session_id: str
    mode_name: str
    messages: tuple[Message, ...]
    config: PluginConfig


@dataclass(frozen=True)
class ModeSpec:
    name: str
    is_active: Callable[[ModeContext], bool]
    tools: tuple[ToolSpec, ...] = ()
    commands: tuple[CommandSpec, ...] = ()
    hooks: tuple[HookSpec, ...] = ()
    prompts: tuple[PromptSpec, ...] = ()
    on_turn_start: Callable[
        [ModeContext],
        None | Awaitable[None],
    ] | None = None
    on_reset: Callable[[ModeContext], None | Awaitable[None]] | None = None
