# -*- coding: utf-8 -*-
"""Interface implemented by terminal transports."""

from __future__ import annotations

from typing import Protocol

from ..capture import BackgroundCapture


class ProcessOwner(Protocol):
    @property
    def returncode(self) -> int | None:
        ...

    async def interrupt(self) -> None:
        ...

    async def terminate(self, grace: float = 2.0) -> None:
        ...


class TerminalBackend(Protocol):
    @property
    def capture(self) -> BackgroundCapture:
        ...

    @property
    def supervisor(self) -> ProcessOwner:
        ...

    @property
    def tty(self) -> bool:
        ...

    @property
    def degraded(self) -> bool:
        ...

    async def write(self, data: bytes) -> None:
        ...

    async def interrupt(self) -> None:
        ...

    async def close(self) -> None:
        ...
