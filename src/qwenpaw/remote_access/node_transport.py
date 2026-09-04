# -*- coding: utf-8 -*-
"""Outbound Relay transport and fixed-operation dispatcher for a Node."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from websockets.asyncio.client import connect

from .identity import RelayKeyPair
from .protocol import (
    RelayFrame,
    RelayFrameType,
    RelayOperation,
    decode_frame,
    encode_frame,
)


RelayOperationHandler = Callable[[bytes], Awaitable[bytes]]


class RelayOperationDispatcher:
    """Dispatch only operations registered by trusted QwenPaw code."""

    def __init__(
        self,
        handlers: Mapping[RelayOperation, RelayOperationHandler],
    ) -> None:
        self._handlers = dict(handlers)

    async def dispatch(
        self,
        operation: RelayOperation,
        payload: bytes,
    ) -> bytes:
        """Execute one fixed operation or reject it as unsupported."""
        handler = self._handlers.get(operation)
        if handler is None:
            raise LookupError(f"Unsupported Relay operation: {operation}")
        return await handler(payload)


@dataclass(slots=True)
class _IncomingRequest:
    operation: RelayOperation
    request_id: str
    chunks: list[bytes] = field(default_factory=list)
    size: int = 0


class RelayNodeTransport:
    """Maintain one authenticated outbound Node WSS until it closes."""

    def __init__(
        self,
        dispatcher: RelayOperationDispatcher,
        *,
        max_request_bytes: int = 16 * 1024 * 1024,
        max_streams: int = 32,
    ) -> None:
        self._dispatcher = dispatcher
        self._max_request_bytes = max_request_bytes
        self._max_streams = max_streams
        self._streams: dict[str, _IncomingRequest] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def run(
        self,
        *,
        websocket_url: str,
        ticket: str,
        dpop_nonce: str,
        key_pair: RelayKeyPair,
    ) -> None:
        """Connect with a one-time ticket and serve fixed operations."""
        _validate_websocket_url(websocket_url)
        proof = key_pair.create_proof(
            "GET",
            websocket_url,
            ticket,
            dpop_nonce,
        )
        async with connect(
            websocket_url,
            additional_headers={
                "Authorization": f"RelayTicket {ticket}",
                "DPoP": proof,
            },
            compression=None,
            max_size=self._max_request_bytes + 64 * 1024,
            proxy=None,
        ) as socket:
            try:
                async for wire in socket:
                    if not isinstance(wire, bytes):
                        await self._connection_error(
                            socket,
                            "BINARY_REQUIRED",
                        )
                        continue
                    await self._receive(socket, decode_frame(wire))
            finally:
                tasks = tuple(self._tasks.values())
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                self._tasks.clear()
                self._streams.clear()

    async def _receive(self, socket, frame: RelayFrame) -> None:
        if frame.frame_type is RelayFrameType.PING:
            await socket.send(encode_frame(RelayFrame(RelayFrameType.PONG)))
            return
        if frame.frame_type is RelayFrameType.OPEN:
            await self._open(socket, frame)
            return
        if frame.frame_type is RelayFrameType.DATA:
            await self._data(socket, frame)
            return
        if frame.frame_type is RelayFrameType.END:
            await self._end(socket, frame)
            return
        if frame.frame_type is RelayFrameType.CANCEL:
            self._cancel(frame.stream_id)

    async def _open(self, socket, frame: RelayFrame) -> None:
        assert frame.stream_id is not None
        assert frame.request_id is not None
        if (
            frame.stream_id in self._streams
            or frame.stream_id in self._tasks
            or len(self._streams) + len(self._tasks) >= self._max_streams
        ):
            await self._stream_error(socket, frame.stream_id, "STREAM_LIMIT")
            return
        self._streams[frame.stream_id] = _IncomingRequest(
            operation=RelayOperation(frame.metadata["operation_id"]),
            request_id=frame.request_id,
        )

    async def _data(self, socket, frame: RelayFrame) -> None:
        assert frame.stream_id is not None
        request = self._streams.get(frame.stream_id)
        if request is None:
            await self._stream_error(socket, frame.stream_id, "UNKNOWN_STREAM")
            return
        request.size += len(frame.payload)
        if request.size > self._max_request_bytes:
            self._streams.pop(frame.stream_id, None)
            await self._stream_error(socket, frame.stream_id, "BODY_TOO_LARGE")
            return
        request.chunks.append(frame.payload)

    async def _end(self, socket, frame: RelayFrame) -> None:
        assert frame.stream_id is not None
        request = self._streams.pop(frame.stream_id, None)
        if request is None:
            await self._stream_error(socket, frame.stream_id, "UNKNOWN_STREAM")
            return
        task = asyncio.create_task(
            self._execute(socket, frame.stream_id, request),
        )
        self._tasks[frame.stream_id] = task
        task.add_done_callback(self._operation_finished)

    def _operation_finished(self, task: asyncio.Task[None]) -> None:
        for stream_id, current in tuple(self._tasks.items()):
            if current is task:
                self._tasks.pop(stream_id, None)
                return

    async def _execute(
        self,
        socket,
        stream_id: str,
        request: _IncomingRequest,
    ) -> None:
        try:
            result = await self._dispatcher.dispatch(
                request.operation,
                b"".join(request.chunks),
            )
            await socket.send(
                encode_frame(
                    RelayFrame(
                        RelayFrameType.RESULT_META,
                        stream_id=stream_id,
                        request_id=request.request_id,
                        metadata={"status": "ok"},
                    ),
                ),
            )
            if result:
                await socket.send(
                    encode_frame(
                        RelayFrame(
                            RelayFrameType.DATA,
                            stream_id=stream_id,
                            payload=result,
                        ),
                    ),
                )
            await socket.send(
                encode_frame(
                    RelayFrame(RelayFrameType.END, stream_id=stream_id),
                ),
            )
        except LookupError:
            await self._stream_error(
                socket,
                stream_id,
                "UNSUPPORTED_OPERATION",
            )
        except Exception:
            await self._stream_error(socket, stream_id, "OPERATION_FAILED")

    def _cancel(self, stream_id: str | None) -> None:
        if stream_id is None:
            return
        self._streams.pop(stream_id, None)
        task = self._tasks.get(stream_id)
        if task is not None:
            task.cancel()

    @staticmethod
    async def _stream_error(socket, stream_id: str, code: str) -> None:
        await socket.send(
            encode_frame(
                RelayFrame(
                    RelayFrameType.ERROR,
                    stream_id=stream_id,
                    metadata={"code": code},
                ),
            ),
        )

    @staticmethod
    async def _connection_error(socket, code: str) -> None:
        await RelayNodeTransport._stream_error(socket, "connection", code)


def _validate_websocket_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"wss", "ws"} or not parsed.hostname:
        raise ValueError("Relay URL must be a WebSocket URL")
    if parsed.scheme == "ws" and parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError("Relay URL must use WSS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Relay URL must not contain credentials or queries")
