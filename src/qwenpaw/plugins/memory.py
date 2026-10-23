# -*- coding: utf-8 -*-
"""Memory backend values; construction and shutdown remain host-owned."""

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .messages import Message
from .tools import ToolContext, ToolResult


@dataclass(frozen=True)
class MemoryContext(ToolContext):
    backend_id: str = ""
    language: str = "zh"


class MemoryBackend(Protocol):
    async def start(self, context: MemoryContext) -> None:
        ...

    async def search(
        self,
        context: MemoryContext,
        query: str,
        max_results: int,
    ) -> ToolResult:
        ...

    async def remember(
        self,
        context: MemoryContext,
        messages: tuple[Message, ...],
    ) -> str:
        ...

    async def close(self, context: MemoryContext) -> bool:
        ...


@dataclass(frozen=True)
class MemorySpec:
    id: str
    label: str
    create: Callable[[], MemoryBackend]
    config_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object"},
    )
    secrets: tuple[str, ...] = ()
    prompt: str = ""
    auto_memory_interval: int = 0
    auto_search_max_results: int | None = None


@dataclass(frozen=True)
class MemoryTask:
    task_id: str
    status: str
    result: str | None = None
    error: str | None = None
