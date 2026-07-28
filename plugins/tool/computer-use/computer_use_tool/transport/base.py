# -*- coding: utf-8 -*-
"""Framing-neutral controlled transport contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

ReverseRequestHandler = Callable[
    [Mapping[str, Any]],
    Awaitable[dict[str, Any]],
]


class ComputerUseTransport(ABC):
    """Authenticated request/response transport with reverse policy events."""

    @abstractmethod
    async def connect(self) -> None:
        """Connect and authenticate the native endpoint."""

    @abstractmethod
    async def request(self, message: Mapping[str, Any]) -> dict[str, Any]:
        """Send one request and await its matching response."""

    @abstractmethod
    async def close(self) -> None:
        """Close the transport and fail outstanding requests."""

    @abstractmethod
    def set_reverse_request_handler(
        self,
        handler: ReverseRequestHandler,
    ) -> None:
        """Install the handler for native-initiated policy requests."""
