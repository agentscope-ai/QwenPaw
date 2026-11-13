# -*- coding: utf-8 -*-
"""Hello handshake helpers for chrome backend connections."""

from __future__ import annotations

import asyncio
import json
from typing import Any

try:
    from .protocol_mirror import PROTOCOL_VERSION, contract_snapshot
except ImportError:
    from protocol_mirror import PROTOCOL_VERSION, contract_snapshot

try:
    from .build_fingerprint import BUILD_FINGERPRINT
except ImportError:
    try:
        from build_fingerprint import BUILD_FINGERPRINT
    except ImportError:
        BUILD_FINGERPRINT = {"commit": "unknown", "builtAt": None}


class HandshakeError(RuntimeError):
    """Raised when a backend hello handshake fails."""


class HandshakePermanentError(HandshakeError):
    """Raised when the core rejects hello and retrying cannot help."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "",
        expected_min: int | None = None,
        expected: int | None = None,
        actual: int | None = None,
        advice: str = "",
        raw_message: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.expected_min = expected_min
        self.expected = expected
        self.actual = actual
        self.advice = advice
        self.raw_message = raw_message or {}


class HandshakeTransientError(HandshakeError):
    """Raised when retrying the hello handshake may succeed."""


def _protocol_value(message: dict[str, Any], key: str) -> int | None:
    value = message.get(key)
    return value if isinstance(value, int) else None


def _rejection_advice(
    code: str,
    expected_min: int | None,
    expected: int | None,
    actual: int | None,
) -> str:
    if code == "BROWSER_PROTOCOL_VERSION_MISMATCH":
        if (
            actual is not None
            and expected_min is not None
            and actual < expected_min
        ):
            return "Please upgrade the extension to a compatible version."
        if actual is not None and expected is not None and actual > expected:
            return "Please upgrade QwenPaw core to a compatible version."
        return (
            "Please upgrade the extension or QwenPaw core to compatible "
            "versions."
        )
    return "QwenPaw core permanently rejected the Native Messaging hello."


async def send_hello(
    ws: Any,
    entry_id: str,
    protocol_version: int = PROTOCOL_VERSION,
) -> None:
    """Send bridge hello metadata to a backend websocket."""
    # Contract and build metadata let the core compare this installed host
    # without changing the existing protocol-version handshake fields.
    await ws.send(
        json.dumps(
            {
                "type": "hello",
                "entryId": entry_id,
                "protocolVersion": protocol_version,
                "contract": contract_snapshot(),
                "build": dict(BUILD_FINGERPRINT),
            },
            separators=(",", ":"),
        ),
    )


async def wait_hello_ack(ws: Any, timeout: float = 5.0) -> dict:
    """Wait for and validate hello_ack."""
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise HandshakeTransientError("Hello ack timeout") from exc

    message = json.loads(
        raw.decode("utf-8") if isinstance(raw, bytes) else raw,
    )
    if message.get("type") != "hello_ack" or message.get("status") != "ok":
        code = str(message.get("code") or "")
        expected_min = _protocol_value(
            message,
            "expected_min_protocol_version",
        )
        expected = _protocol_value(message, "expected_protocol_version")
        actual = _protocol_value(message, "actual_protocol_version")
        raise HandshakePermanentError(
            f"Hello rejected: {message}",
            code=code,
            expected_min=expected_min,
            expected=expected,
            actual=actual,
            advice=_rejection_advice(code, expected_min, expected, actual),
            raw_message=message,
        )
    return message


__all__ = [
    "HandshakeError",
    "HandshakePermanentError",
    "HandshakeTransientError",
    "send_hello",
    "wait_hello_ack",
]
