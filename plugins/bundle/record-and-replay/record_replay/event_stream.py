# -*- coding: utf-8 -*-
"""Plugin-owned EventStream v1 client for the host-managed helper."""

from __future__ import annotations

import asyncio
import json
import socket
import struct
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from qwenpaw.app.computer_use import HostRuntimeProvider, RuntimeCapability

from .errors import RecordingProtocolError

PROTOCOL_VERSION = 2
CONTRACT_NAME = "event_stream"
CONTRACT_VERSION = 1
_MAX_FRAME_BYTES = 64 * 1024 * 1024
_CONNECT_TIMEOUT_SECONDS = 5.0
_REQUEST_TIMEOUT_SECONDS = 10.0
_ACQUIRE_ATTEMPTS = 3
_ACQUIRE_RETRY_SECONDS = 0.5


class EventStreamClient:
    """Own one authenticated EventStream connection.

    This is intentionally not a general RPC client. It understands one
    contract, keeps the staging root returned by that authenticated hello, and
    never exposes the capability secret to product or model-facing schemas.
    """

    def __init__(self) -> None:
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._capability: RuntimeCapability | None = None
        self._artifact_root: Path | None = None
        self._lock = asyncio.Lock()

    @property
    def artifact_root(self) -> Path:
        """Return the staging root bound by the authenticated hello."""
        if self._artifact_root is None:
            raise RecordingProtocolError(
                "event_stream artifact root unavailable",
            )
        return self._artifact_root

    async def available(self) -> bool:
        """Whether this helper advertises EventStream v1."""
        try:
            async with self._lock:
                await self._ensure_connected()
            return True
        except RecordingProtocolError:
            return False

    async def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float = _REQUEST_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Execute one EventStream request in connection order."""
        if not method.startswith("event_stream."):
            raise RecordingProtocolError("invalid EventStream method")
        async with self._lock:
            await self._ensure_connected()
            message = {
                "request_id": uuid4().hex,
                "method": method,
                "params": dict(params or {}),
                "meta": {
                    "session_id": "desktop-recording",
                    "turn_id": "",
                    "deadline_ms": max(100, int(timeout * 1000)),
                },
                "protocol_version": PROTOCOL_VERSION,
            }
            try:
                await asyncio.wait_for(self._write(message), timeout)
                response = await asyncio.wait_for(self._read(), timeout)
            except (
                asyncio.TimeoutError,
                OSError,
                RecordingProtocolError,
                ValueError,
            ) as exc:
                await self._close_locked(invalidate=True)
                raise RecordingProtocolError(
                    "EventStream native runtime disconnected",
                ) from exc
            if response.get("request_id") != message["request_id"]:
                await self._close_locked(invalidate=True)
                raise RecordingProtocolError(
                    "EventStream response id mismatch",
                )
            if response.get("ok") is not True:
                error = response.get("error")
                code = (
                    str(error.get("code") or "native_error")
                    if isinstance(error, Mapping)
                    else "native_error"
                )
                detail = (
                    str(error.get("message") or code)
                    if isinstance(error, Mapping)
                    else code
                )
                raise RecordingProtocolError(f"{code}:{detail}")
            result = response.get("result")
            if not isinstance(result, dict):
                raise RecordingProtocolError(
                    "EventStream response has no result",
                )
            return result

    async def status(
        self,
        *,
        recording_id: str | None = None,
    ) -> dict[str, Any]:
        """Return low-sensitivity native recording and permission state."""
        params = (
            {"recording_id": recording_id}
            if recording_id is not None
            else None
        )
        return await self.request("event_stream.status", params)

    async def close(self) -> None:
        """Close the connection so Helper-side ownership is released."""
        async with self._lock:
            await self._close_locked(invalidate=False)

    async def _ensure_connected(self) -> None:
        if self._writer is not None:
            return
        if sys.platform != "darwin" or not hasattr(socket, "AF_UNIX"):
            raise RecordingProtocolError(
                "EventStream is not available on this platform",
            )
        capability = None
        for attempt in range(_ACQUIRE_ATTEMPTS):
            capability = await asyncio.to_thread(
                HostRuntimeProvider.acquire_capability,
            )
            if capability is not None:
                break
            if attempt + 1 < _ACQUIRE_ATTEMPTS:
                await asyncio.sleep(_ACQUIRE_RETRY_SECONDS)
        if (
            capability is None
            or capability.protocol_version != PROTOCOL_VERSION
        ):
            raise RecordingProtocolError(
                "EventStream native runtime unavailable",
            )
        try:
            # RuntimeCapability intentionally exposes these only to controlled
            # native clients, never to request bodies or tool schemas.
            # pylint: disable=protected-access
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(capability._pipe_name),
                _CONNECT_TIMEOUT_SECONDS,
            )
            self._reader = reader
            self._writer = writer
            self._capability = capability
            hello = {
                "request_id": "event-stream-hello",
                "method": "hello",
                "params": {
                    "capability": capability._secret,
                    "protocol_version": PROTOCOL_VERSION,
                    "contract": CONTRACT_NAME,
                },
                "meta": {
                    "session_id": "",
                    "turn_id": "",
                    "deadline_ms": 5000,
                },
                "protocol_version": PROTOCOL_VERSION,
            }
            await asyncio.wait_for(
                self._write(hello),
                _CONNECT_TIMEOUT_SECONDS,
            )
            response = await asyncio.wait_for(
                self._read(),
                _CONNECT_TIMEOUT_SECONDS,
            )
            self._accept_hello(response)
        except (asyncio.TimeoutError, OSError, ValueError) as exc:
            await self._close_locked(invalidate=True)
            raise RecordingProtocolError(
                "EventStream native runtime unavailable",
            ) from exc
        except RecordingProtocolError:
            await self._close_locked(invalidate=False)
            raise

    def _accept_hello(self, response: Mapping[str, Any]) -> None:
        if response.get("request_id") != "event-stream-hello":
            raise RecordingProtocolError("invalid EventStream hello response")
        if response.get("ok") is not True:
            error = response.get("error")
            code = (
                str(error.get("code") or "unsupported_contract")
                if isinstance(error, Mapping)
                else "unsupported_contract"
            )
            raise RecordingProtocolError(code)
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise RecordingProtocolError("invalid EventStream hello result")
        contracts = result.get("contracts")
        try:
            version = (
                int(contracts.get(CONTRACT_NAME, 0))
                if isinstance(contracts, Mapping)
                else 0
            )
        except (TypeError, ValueError) as exc:
            raise RecordingProtocolError(
                "invalid EventStream contract",
            ) from exc
        root = result.get("artifact_root")
        if (
            result.get("protocol_version") != PROTOCOL_VERSION
            or version != CONTRACT_VERSION
            or not isinstance(root, str)
        ):
            raise RecordingProtocolError("incompatible EventStream contract")
        path = Path(root)
        if not path.is_absolute() or ".." in path.parts:
            raise RecordingProtocolError("invalid EventStream artifact root")
        self._artifact_root = path

    async def _write(self, message: Mapping[str, Any]) -> None:
        writer = self._writer
        if writer is None:
            raise RecordingProtocolError("EventStream connection is closed")
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        if not payload or len(payload) > _MAX_FRAME_BYTES:
            raise RecordingProtocolError(
                "EventStream request frame is invalid",
            )
        writer.write(struct.pack("<I", len(payload)) + payload)
        await writer.drain()

    async def _read(self) -> dict[str, Any]:
        reader = self._reader
        if reader is None:
            raise RecordingProtocolError("EventStream connection is closed")
        header = await reader.readexactly(4)
        length = struct.unpack("<I", header)[0]
        if length <= 0 or length > _MAX_FRAME_BYTES:
            raise RecordingProtocolError(
                "EventStream response frame is invalid",
            )
        value = json.loads(await reader.readexactly(length))
        if not isinstance(value, dict):
            raise RecordingProtocolError(
                "EventStream response is not an object",
            )
        return value

    async def _close_locked(self, *, invalidate: bool) -> None:
        writer, self._writer = self._writer, None
        self._reader = None
        self._artifact_root = None
        capability, self._capability = self._capability, None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
        if invalidate and capability is not None:
            HostRuntimeProvider.invalidate_capability(capability)


__all__ = ["CONTRACT_NAME", "CONTRACT_VERSION", "EventStreamClient"]
