# -*- coding: utf-8 -*-
"""Outbound Relay transport and fixed-operation dispatcher for a Node."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import (
    AsyncGenerator,
    AsyncIterator,
    Awaitable,
    Callable,
    Mapping,
)
from contextlib import AbstractAsyncContextManager, aclosing
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from websockets.asyncio.client import connect

from .identity import RelayKeyPair
from .run_state import RelayRuns
from .protocol import (
    RelayFrame,
    RelayFrameType,
    RelayOperation,
    decode_frame,
    encode_frame,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RelayResponse:
    """An upstream response whose body stays streamed and bounded."""

    status: int
    content_type: str
    body: AsyncIterator[bytes]
    headers: dict[str, str] = field(default_factory=dict)


RelayOperationHandler = Callable[
    [bytes],
    Awaitable[AbstractAsyncContextManager[RelayResponse]],
]


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
    ) -> AbstractAsyncContextManager[RelayResponse]:
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
        runs: RelayRuns | None = None,
        sync_runs: (
            Callable[[str, list[str]], Awaitable[dict[str, list[str]]]] | None
        ) = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._max_request_bytes = max_request_bytes
        self._max_streams = max_streams
        self._runs = runs or RelayRuns()
        self._sync_runs = sync_runs
        self._acknowledged: set[str] = set()
        self._streams: dict[str, _IncomingRequest] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._response_windows: dict[str, asyncio.Queue[None]] = {}
        self.connected = False
        self.connected_at = 0.0

    async def run(
        self,
        *,
        websocket_url: str,
        ticket: str,
        dpop_nonce: str,
        key_pair: RelayKeyPair,
        node_id: str,
    ) -> None:
        """Connect with a one-time ticket and serve fixed operations."""
        _validate_websocket_url(websocket_url)
        self._runs.select_node(node_id)
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
            await self._report_runs(socket, node_id)
            self.connected = True
            self.connected_at = asyncio.get_running_loop().time()
            heartbeat = asyncio.create_task(self._heartbeat(socket, node_id))
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
                self.connected = False
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
                tasks = tuple(self._tasks.values())
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                self._tasks.clear()
                self._streams.clear()
                self._response_windows.clear()

    async def _report_runs(self, socket, node_id: str) -> None:
        self._runs.changed.clear()
        if self._sync_runs is None:
            report = self._runs.report()
        else:
            finished = list(self._acknowledged)
            report = await self._sync_runs(node_id, finished)
            self._acknowledged.difference_update(finished)
        await socket.send(
            encode_frame(
                RelayFrame(
                    RelayFrameType.HELLO,
                    metadata=report,
                ),
            ),
        )

    async def _heartbeat(self, socket, node_id: str) -> None:
        try:
            while True:
                try:
                    await asyncio.wait_for(self._runs.changed.wait(), 5)
                except asyncio.TimeoutError:
                    pass
                await self._report_runs(socket, node_id)
        except Exception:
            await socket.close()
            raise

    async def _receive(self, socket, frame: RelayFrame) -> None:
        if frame.frame_type is RelayFrameType.HELLO:
            finished = frame.metadata["finished"]
            if self._sync_runs is None:
                self._runs.acknowledge(finished)
            elif finished:
                self._acknowledged.update(finished)
                self._runs.changed.set()
            return
        if frame.frame_type is RelayFrameType.WINDOW_UPDATE:
            assert frame.stream_id is not None
            window = self._response_windows.get(frame.stream_id)
            if window is not None and not window.full():
                window.put_nowait(None)
            return
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
        window: asyncio.Queue[None] = asyncio.Queue(maxsize=8)
        for _ in range(8):
            window.put_nowait(None)
        self._response_windows[frame.stream_id] = window
        task.add_done_callback(self._operation_finished)

    def _operation_finished(self, task: asyncio.Task[None]) -> None:
        for stream_id, current in tuple(self._tasks.items()):
            if current is task:
                self._tasks.pop(stream_id, None)
                self._response_windows.pop(stream_id, None)
                return

    async def _execute(
        self,
        socket,
        stream_id: str,
        request: _IncomingRequest,
    ) -> None:
        try:
            response = await self._dispatcher.dispatch(
                request.operation,
                b"".join(request.chunks),
            )
            async with response as result:
                await socket.send(
                    encode_frame(
                        RelayFrame(
                            RelayFrameType.RESULT_META,
                            stream_id=stream_id,
                            request_id=request.request_id,
                            metadata={
                                "status": result.status,
                                "content_type": result.content_type,
                                "headers": result.headers,
                            },
                        ),
                    ),
                )
                async with aclosing(
                    _response_chunks(
                        result.body,
                        sse=result.content_type.startswith(
                            "text/event-stream",
                        ),
                    ),
                ) as chunks:
                    async for chunk in chunks:
                        for offset in range(0, len(chunk), 64 * 1024):
                            await self._response_windows[stream_id].get()
                            await socket.send(
                                encode_frame(
                                    RelayFrame(
                                        RelayFrameType.DATA,
                                        stream_id=stream_id,
                                        payload=chunk[
                                            offset : offset + 64 * 1024
                                        ],
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
        except Exception as exc:
            logger.warning("Relay operation failed: %s", type(exc).__name__)
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


async def _response_chunks(
    body: AsyncIterator[bytes],
    *,
    sse: bool,
) -> AsyncGenerator[bytes, None]:
    """Coalesce small SSE writes while keeping first output immediate."""
    if not sse:
        async for chunk in body:
            for offset in range(0, len(chunk), 64 * 1024):
                yield chunk[offset : offset + 64 * 1024]
        return

    queue: asyncio.Queue[bytes | Exception | None] = asyncio.Queue(maxsize=1)

    async def read() -> None:
        try:
            async for chunk in body:
                for offset in range(0, len(chunk), 4096):
                    await queue.put(chunk[offset : offset + 4096])
        except Exception as error:
            await queue.put(error)
        else:
            await queue.put(None)

    reader = asyncio.create_task(read())
    pending: bytes | None = None
    first = True
    try:
        while True:
            item = pending if pending is not None else await queue.get()
            pending = None
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            if first:
                first = False
                yield item
                continue
            batch = bytearray(item)
            deadline = asyncio.get_running_loop().time() + 0.05
            while len(batch) < 4096:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), remaining)
                except asyncio.TimeoutError:
                    break
                if item is None:
                    yield bytes(batch)
                    return
                if isinstance(item, Exception):
                    raise item
                if len(batch) + len(item) > 4096:
                    pending = item
                    break
                batch.extend(item)
            yield bytes(batch)
    finally:
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)


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
