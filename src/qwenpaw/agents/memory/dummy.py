# -*- coding: utf-8 -*-
"""No-op memory manager – disables all memory functionality."""

from agentscope.message import Msg
from agentscope.middleware import MiddlewareBase
from agentscope.tool import ToolChunk

from .base_memory_manager import BaseMemoryManager, memory_registry


@memory_registry.register("none")
class NoopMemoryManager(BaseMemoryManager):
    """A no-op memory manager that disables all memory features.

    All tool/prompt/middleware methods return empty results. Use this
    backend when you want to run QwenPaw without any memory system.
    """

    enabled = False

    async def start(self) -> None:
        """No-op: nothing to initialize."""

    def get_memory_prompt(self) -> str:
        """Return empty prompt – no memory guidance needed."""
        return ""

    def is_memory_search_enabled(self) -> bool:
        """Return false because the disabled backend exposes no tools."""
        return False

    async def memory_search(
        self,
        query: str,
        max_results: int = 5,
        **kwargs,
    ) -> ToolChunk:
        """Reject searches against the disabled backend."""
        del query, max_results, kwargs
        raise RuntimeError("Memory manager is disabled")

    async def auto_memory(
        self,
        messages: list[Msg],
        **kwargs,
    ) -> str:
        """Discard auto-memory requests for the disabled backend."""
        del messages, kwargs
        return ""

    def build_middlewares(self) -> list[MiddlewareBase]:
        """Return empty list – no memory middlewares."""
        return []

    def get_auto_memory_interval(self) -> int:
        """Return 0 – disable auto-memory."""
        return 0
