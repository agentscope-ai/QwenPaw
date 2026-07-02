# -*- coding: utf-8 -*-
"""No-op memory manager – disables all memory functionality."""
from collections.abc import Callable

from agentscope.middleware import MiddlewareBase
from agentscope.tool import ToolChunk

from .base_memory_manager import BaseMemoryManager, memory_registry


@memory_registry.register("none")
class NoopMemoryManager(BaseMemoryManager):
    """A no-op memory manager that disables all memory features.

    All tool/prompt/middleware methods return empty results. Use this
    backend when you want to run QwenPaw without any memory system.
    """

    async def start(self) -> None:
        """No-op: nothing to initialize."""

    async def close(self) -> bool:
        """No-op: nothing to release."""
        return True

    def get_memory_prompt(self) -> str:
        """Return empty prompt – no memory guidance needed."""
        return ""

    def list_memory_tools(self) -> list[Callable[..., ToolChunk]]:
        """Return empty list – no memory tools exposed."""
        return []

    def build_middlewares(self) -> list[MiddlewareBase]:
        """Return empty list – no memory middlewares."""
        return []

    def get_auto_memory_interval(self) -> int:
        """Return 0 – disable auto-memory."""
        return 0
