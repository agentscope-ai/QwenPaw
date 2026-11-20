# -*- coding: utf-8 -*-
"""Common transport and JSON-RPC exceptions."""

from __future__ import annotations
import asyncio
from collections.abc import Sequence

PathPart = str | int


class FrameError(Exception):
    """Base class for strict stdio framing and transport failures."""


class FrameProtocolError(FrameError):
    """Report malformed framing or invalid UTF-8."""


class FrameLimitError(FrameProtocolError):
    """Report a frame or header exceeding its configured bound."""


class FrameEOFError(FrameError):
    """Report clean EOF at a frame boundary."""


class FrameTimeoutError(FrameError):
    """Report a read, queue, or write deadline expiry."""


class FrameClosedError(FrameError):
    """Report an operation attempted on a closed transport."""


class FrameWriteError(FrameError):
    """Report an OS or stream failure while writing a frame."""


class ProtocolValidationError(ValueError):
    """Report an invalid JSON-RPC envelope or versioned DTO."""

    code = "invalid_params"

    def __init__(
        self,
        message: str,
        *,
        path: Sequence[PathPart] = (),
        reason_code: str = "INVALID_PARAMS",
    ) -> None:
        self.path = tuple(path)
        self.reason_code = reason_code
        super().__init__(message)


class RpcError(Exception):
    """Report a remote JSON-RPC error response."""

    def __init__(
        self,
        code: int,
        message: str,
        *,
        data: object = None,
    ) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"{code}: {message}")


class RpcTimeoutError(TimeoutError):
    """Report a request deadline expiry."""


class RpcClosedError(ConnectionError):
    """Report a request attempted after peer shutdown."""


class RpcCancelledError(asyncio.CancelledError):
    """Report a request cancelled through the protocol."""
