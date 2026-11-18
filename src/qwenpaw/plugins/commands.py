# -*- coding: utf-8 -*-
"""Public slash-command declarations and controlled input/reply results."""

from dataclasses import dataclass
from typing import Callable, Literal, Awaitable

from .messages import Message
from .tools import ToolContext


@dataclass(frozen=True)
class CommandContext(ToolContext):
    messages: tuple[Message, ...] = ()


@dataclass(frozen=True)
class CommandResult:
    action: Literal["continue", "reply", "replace_input"] = "continue"
    message: Message | None = None
    messages: tuple[Message, ...] = ()


@dataclass(frozen=True)
class CommandSpec:
    name: str
    handler: Callable[
        [CommandContext, str],
        CommandResult | Awaitable[CommandResult],
    ]
    aliases: tuple[str, ...] = ()
    help_text: str = ""
