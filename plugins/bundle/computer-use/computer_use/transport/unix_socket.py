# -*- coding: utf-8 -*-
"""Unix domain socket transport for the host-managed Computer Use helper.

This mirrors :class:`WindowsPipeTransport` on macOS. The wire protocol,
handshake, request correlation, and reverse app-approval behavior are
identical; only the byte transport differs (an ``asyncio`` Unix domain
socket instead of a Windows named pipe), so no background thread or
overlapped I/O machinery is needed.
"""

# The capability's endpoint name and secret are deliberately private so they
# cannot leak into tool inputs; a transport is their only intended reader.
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
import contextvars
import json
import socket
import struct
import time
from collections.abc import Mapping
from typing import Any

from qwenpaw.app.computer_use.runtime import RuntimeCapability

from ..protocol import ComputerUseProtocolError, approval_reply
from .base import ComputerUseTransport, ReverseRequestHandler

_MAX_FRAME_BYTES = 64 * 1024 * 1024
_CONNECT_TIMEOUT_SECONDS = 5
_APPROVAL_POLL_SECONDS = 0.25


class UnixSocketTransport(ComputerUseTransport):
    """Length-prefixed JSON transport with native reverse-policy support."""

    def __init__(self, capability: RuntimeCapability) -> None:
        self._capability = capability
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._write_lock = asyncio.Lock()
        self._reverse_handler: ReverseRequestHandler | None = None
        self._reverse_context: contextvars.Context | None = None
        self._approvals_in_flight = 0
        self._closed = False

    async def connect(self) -> None:
        """Open the host-provided socket and perform the protocol handshake."""
        if self._writer is not None:
            return
        if not hasattr(socket, "AF_UNIX"):
            raise ComputerUseProtocolError(
                "runtime_unavailable",
                "Computer Use Unix socket transport requires a POSIX host.",
            )
        self._loop = asyncio.get_running_loop()
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self._capability._pipe_name),
                _CONNECT_TIMEOUT_SECONDS,
            )
        except (OSError, asyncio.TimeoutError) as exc:
            raise ComputerUseProtocolError(
                "runtime_unavailable",
                "Computer Use native runtime is not running.",
            ) from exc
        self._reader_task = asyncio.ensure_future(self._reader_loop())
        hello = {
            "request_id": "hello",
            "method": "hello",
            "params": {
                "capability": self._capability._secret,
                "protocol_version": self._capability.protocol_version,
            },
            "meta": {"session_id": "", "turn_id": "", "deadline_ms": 5000},
            "protocol_version": self._capability.protocol_version,
        }
        response = await self.request(hello)
        result = response.get("result")
        if (
            not isinstance(result, Mapping)
            or int(result.get("protocol_version", 0))
            != self._capability.protocol_version
        ):
            await self.close()
            raise ComputerUseProtocolError(
                "protocol_mismatch",
                "Computer Use helper protocol is incompatible with this "
                "plugin.",
            )

    async def request(self, message: Mapping[str, Any]) -> dict[str, Any]:
        """Send a request and await its native response by request id."""
        if self._writer is None or self._closed:
            raise ComputerUseProtocolError(
                "runtime_unavailable",
                "Computer Use native runtime is unavailable.",
            )
        request_id = str(message.get("request_id") or "")
        if not request_id:
            raise ComputerUseProtocolError(
                "invalid_request",
                "Computer Use request is missing its request identifier.",
            )
        future: asyncio.Future[
            dict[str, Any]
        ] = asyncio.get_running_loop().create_future()
        if request_id in self._pending:
            raise ComputerUseProtocolError(
                "duplicate_request",
                "Computer Use request identifier is already in use.",
            )
        self._pending[request_id] = future
        # The helper only issues reverse approval requests while it is
        # blocked serving this request, so snapshot the caller's context
        # (session, agent, user, channel) for the approval coroutine.
        self._reverse_context = contextvars.copy_context()
        meta = message.get("meta")
        timeout_ms = (
            int(meta.get("deadline_ms", 10000))
            if isinstance(meta, Mapping)
            else 10000
        )
        timeout = max(0.1, timeout_ms / 1000)
        try:
            try:
                await asyncio.wait_for(
                    self._write_message(dict(message)),
                    timeout,
                )
            except Exception:
                # A failed or timed-out write may leave a partial frame on the
                # socket, so the connection can no longer be trusted.
                future.cancel()
                await self.close()
                raise
            return await self._await_response(future, timeout)
        except asyncio.TimeoutError as exc:
            raise ComputerUseProtocolError(
                "request_timeout",
                "Computer Use request timed out.",
            ) from exc
        finally:
            self._pending.pop(request_id, None)

    async def _await_response(
        self,
        future: asyncio.Future[dict[str, Any]],
        timeout: float,
    ) -> dict[str, Any]:
        """Await a response without charging user approval time as timeout.

        The helper blocks serving a request while a reverse app approval
        waits for the user, so the machine deadline pauses until the
        approval resolves and the helper then gets a fresh execution window.
        """
        deadline = time.monotonic() + timeout
        while True:
            if self._approvals_in_flight > 0:
                deadline = time.monotonic() + timeout
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                future.cancel()
                raise asyncio.TimeoutError
            try:
                return await asyncio.wait_for(
                    asyncio.shield(future),
                    min(remaining, _APPROVAL_POLL_SECONDS),
                )
            except asyncio.TimeoutError:
                continue

    async def close(self) -> None:
        """Close the socket and reject every pending request."""
        if self._closed:
            return
        self._closed = True
        writer, self._writer = self._writer, None
        self._reader = None
        task, self._reader_task = self._reader_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except (
                Exception
            ):  # noqa: BLE001 - closing a broken socket may raise
                pass
        self._fail_pending(
            "runtime_disconnected",
            "Computer Use connection closed.",
        )

    def set_reverse_request_handler(
        self,
        handler: ReverseRequestHandler,
    ) -> None:
        self._reverse_handler = handler

    async def _write_message(self, message: dict[str, Any]) -> None:
        writer = self._writer
        if writer is None:
            raise ComputerUseProtocolError(
                "runtime_disconnected",
                "Computer Use connection is closed.",
            )
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        if len(payload) > _MAX_FRAME_BYTES:
            raise ComputerUseProtocolError(
                "frame_too_large",
                "Computer Use request exceeds the transport limit.",
            )
        async with self._write_lock:
            writer.write(struct.pack("<I", len(payload)) + payload)
            await writer.drain()

    async def _reader_loop(self) -> None:
        reader = self._reader
        if reader is None:
            return
        try:
            while not self._closed:
                message = await self._read_message(reader)
                if message.get("method") == "request_app_approval":
                    self._schedule_reverse_request(message)
                else:
                    self._resolve_response(message)
        except (asyncio.CancelledError, asyncio.IncompleteReadError):
            pass
        except Exception as exc:  # noqa: BLE001 - transport boundary
            if not self._closed:
                self._fail_pending(
                    "runtime_disconnected",
                    f"Computer Use connection failed: {exc}",
                )

    async def _read_message(
        self,
        reader: asyncio.StreamReader,
    ) -> dict[str, Any]:
        header = await reader.readexactly(4)
        frame_size = struct.unpack("<I", header)[0]
        if not 0 < frame_size <= _MAX_FRAME_BYTES:
            raise ComputerUseProtocolError(
                "invalid_frame",
                "Invalid Computer Use frame size.",
            )
        payload = await reader.readexactly(frame_size)
        value = json.loads(payload.decode("utf-8"))
        if not isinstance(value, dict):
            raise ComputerUseProtocolError(
                "invalid_frame",
                "Invalid Computer Use message.",
            )
        return value

    def _schedule_reverse_request(self, message: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None:
            return
        # Pause pending request deadlines while the user decides.
        self._approvals_in_flight += 1
        context = self._reverse_context
        # Replay the request-time context so the approval coroutine keeps the
        # session/agent/user/channel it needs; the bare reader-task context
        # would drop those contextvars.
        if context is not None:
            loop.create_task(
                self._reply_to_reverse_request(message),
                context=context,
            )
        else:
            loop.create_task(self._reply_to_reverse_request(message))

    async def _reply_to_reverse_request(self, message: dict[str, Any]) -> None:
        try:
            await self._handle_reverse_request(message)
        finally:
            self._approvals_in_flight -= 1

    async def _handle_reverse_request(self, message: dict[str, Any]) -> None:
        request_id = str(message.get("request_id") or "")
        handler = self._reverse_handler
        decision = {"allowed": False, "source": "invalid"}
        if request_id and handler is not None:
            try:
                decision = await handler(message)
            except Exception:  # noqa: BLE001 - fail closed at the socket edge
                decision = {"allowed": False, "source": "error"}
        reply = approval_reply(
            request_id,
            allowed=bool(decision.get("allowed")),
            source=str(decision.get("source") or "unknown"),
        )
        try:
            await self._write_message(reply)
        except Exception:
            self._fail_pending(
                "runtime_disconnected",
                "Computer Use approval reply could not reach the native "
                "runtime.",
            )

    def _resolve_response(self, message: dict[str, Any]) -> None:
        request_id = str(message.get("request_id") or "")
        future = self._pending.get(request_id)
        if future is None or future.done():
            return
        future.set_result(message)

    def _fail_pending(self, code: str, message: str) -> None:
        futures = list(self._pending.values())
        self._pending.clear()
        for future in futures:
            if not future.done():
                future.set_exception(ComputerUseProtocolError(code, message))
