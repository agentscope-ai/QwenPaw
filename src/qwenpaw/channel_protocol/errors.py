# -*- coding: utf-8 -*-
"""Errors raised by Channel protocol primitives."""

from __future__ import annotations

from collections.abc import Sequence


from ..plugins.execution.errors import (  # pylint: disable=unused-import
    FrameError,
    FrameProtocolError,
    FrameLimitError,
    FrameEOFError,
    FrameTimeoutError,
    FrameClosedError,
    FrameWriteError,
    ProtocolValidationError,
    RpcError,
    RpcTimeoutError,
    RpcClosedError,
    RpcCancelledError,
)

PathPart = str | int

RPC_LIFECYCLE_ERROR = -32010
RPC_FENCING_ERROR = -32011
RPC_AUTH_ERROR = -32012
RPC_CAPABILITY_ERROR = -32013
RPC_RESPONSE_OPEN_FAILED = -32014


class DescriptorValidationError(ValueError):
    """Report an invalid descriptor or related pure value model."""

    code = "descriptor_invalid"

    def __init__(
        self,
        message: str,
        *,
        path: Sequence[PathPart] = (),
    ) -> None:
        self.path = tuple(path)
        super().__init__(message)


class ArtifactValidationError(ValueError):
    """Report an invalid Channel artifact, lock, or release manifest."""

    code = "artifact_invalid"

    def __init__(
        self,
        message: str,
        *,
        path: Sequence[PathPart] = (),
    ) -> None:
        self.path = tuple(path)
        super().__init__(message)


class SecretHandleInvalidError(ValueError):
    """Report an unknown or generation-mismatched secret handle."""


class SecretHandleConsumedError(ValueError):
    """Report a secret handle whose single consumption was attempted."""


class PlatformAuthenticationError(ValueError):
    """Report rejected credentials without carrying their secret value."""


def validation_error(
    message: str,
    *,
    path: Sequence[PathPart] = (),
) -> DescriptorValidationError:
    """Build the stable validation exception used by pure models."""
    return DescriptorValidationError(message, path=path)
