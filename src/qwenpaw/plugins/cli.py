# -*- coding: utf-8 -*-
"""Terminal command definitions and one managed terminal invocation."""

from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol, TypeVar

import click

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

    def run(self, operation: Awaitable[T]) -> T:
        """Wait for an async operation in this invocation's owned loop."""
        return self._run(operation)


@dataclass(frozen=True)
class CliSpec:
    """Bind a manifest CLI ID to a fresh Click command or command group."""

    id: str
    build: Callable[[CliContext], click.Command]
