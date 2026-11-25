# -*- coding: utf-8 -*-
"""Terminal command definitions and one managed terminal invocation."""

from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from typing import (
    AsyncContextManager,
    AsyncIterator,
    Awaitable,
    Callable,
    Protocol,
    TypeVar,
)

import click
from httpx import AsyncClient

from .resources import ResourceScope
from .storage import PluginConfig, PluginStorage
from .logging import PluginLogger

T = TypeVar("T")


class _Runner(Protocol):
    def __call__(self, operation: Awaitable[T]) -> T:
        ...


@dataclass(frozen=True)
class CliContext:
    """Terminal identity and SDK services; run async operations on one loop.

    Factories and group setup only construct definitions and parse options.
    Use resources from execution callbacks or plugin activation hooks.
    Click input and output stay on the calling thread.
    """

    plugin_id: str
    config: PluginConfig
    storage: PluginStorage
    resources: ResourceScope
    logger: PluginLogger
    host: str
    port: int
    _run: _Runner = field(repr=False)
    _local_runtime_api: (
        Callable[[], AsyncContextManager[AsyncClient | None]] | None
    ) = field(default=None, repr=False, compare=False)

    def run(self, operation: Awaitable[T]) -> T:
        """Wait for an async operation in this invocation's owned loop."""
        return self._run(operation)

    @asynccontextmanager
    async def local_runtime_api(self) -> AsyncIterator[AsyncClient | None]:
        """Open this profile's App, or yield None when its endpoint is offline.

        A responding endpoint with a different or unverified owner raises
        an error before the command can use shared files offline.
        """
        if self._local_runtime_api is None:
            yield None
        else:
            async with self._local_runtime_api() as client:
                yield client


@dataclass(frozen=True)
class CliSpec:
    """Bind a manifest CLI ID to a fresh Click command or command group."""

    id: str
    build: Callable[[CliContext], click.Command]
