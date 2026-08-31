# -*- coding: utf-8 -*-
"""Non-blocking, bounded capture for pipes, PTYs and threaded backends."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class CaptureChunk:
    data: bytes
    cursor: int
    original_bytes: int
    omitted_bytes: int
    eof: bool


class BackgroundCapture:
    """Continuously drain output into a cursor-addressed bounded byte ring.

    Producers never await consumers. Once the retained capacity is reached,
    old bytes are evicted and accounted for instead of applying backpressure
    to the child process.
    """

    def __init__(self, max_retained_bytes: int = 1024 * 1024) -> None:
        if max_retained_bytes <= 0:
            raise ValueError("max_retained_bytes must be positive")
        self.max_retained_bytes = max_retained_bytes
        self._buffer = bytearray()
        self._start_cursor = 0
        self._end_cursor = 0
        self._eof = False
        self._changed = asyncio.Event()
        self._reader_task: asyncio.Task[None] | None = None
        self._error: BaseException | None = None

    @property
    def start_cursor(self) -> int:
        return self._start_cursor

    @property
    def end_cursor(self) -> int:
        return self._end_cursor

    @property
    def total_bytes(self) -> int:
        return self._end_cursor

    @property
    def eof(self) -> bool:
        return self._eof

    @property
    def error(self) -> BaseException | None:
        return self._error

    def append(self, data: bytes) -> None:
        """Append bytes from an event-loop callback without blocking."""
        if not data or self._eof:
            return
        self._buffer.extend(data)
        self._end_cursor += len(data)
        overflow = len(self._buffer) - self.max_retained_bytes
        if overflow > 0:
            del self._buffer[:overflow]
            self._start_cursor += overflow
        self._changed.set()

    def mark_eof(self, error: BaseException | None = None) -> None:
        self._eof = True
        self._error = error
        self._changed.set()

    def poll(self, cursor: int, max_bytes: int) -> CaptureChunk:
        max_bytes = max(1, max_bytes)
        requested = max(0, cursor)
        omitted = max(0, self._start_cursor - requested)
        actual = max(requested, self._start_cursor)
        offset = actual - self._start_cursor
        data = bytes(self._buffer[offset : offset + max_bytes])
        next_cursor = actual + len(data)
        return CaptureChunk(
            data=data,
            cursor=next_cursor,
            original_bytes=self._end_cursor,
            omitted_bytes=omitted,
            eof=self._eof,
        )

    def retained_since(self, cursor: int) -> tuple[bytes, int, int]:
        """Return retained bytes since cursor for internal protocol scans."""
        actual = max(cursor, self._start_cursor)
        offset = actual - self._start_cursor
        return bytes(self._buffer[offset:]), actual, self._end_cursor

    def discard_retained(self) -> None:
        """Discard buffered bytes while preserving the monotonic cursor."""
        self._buffer.clear()
        self._start_cursor = self._end_cursor

    async def wait_for_change(self, cursor: int, timeout: float) -> bool:
        if self._end_cursor > cursor or self._eof:
            return True
        self._changed.clear()
        if self._end_cursor > cursor or self._eof:
            return True
        try:
            await asyncio.wait_for(
                self._changed.wait(),
                timeout=max(0.0, timeout),
            )
            return True
        except asyncio.TimeoutError:
            return False

    def start_stream_reader(
        self,
        reader: asyncio.StreamReader,
        *,
        chunk_size: int = 64 * 1024,
    ) -> None:
        if self._reader_task is not None:
            raise RuntimeError("capture reader already started")

        async def drain() -> None:
            try:
                while True:
                    data = await reader.read(chunk_size)
                    if not data:
                        self.mark_eof()
                        return
                    self.append(data)
                    await asyncio.sleep(0)
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # noqa: BLE001
                self.mark_eof(exc)

        self._reader_task = asyncio.create_task(
            drain(),
            name="qwenpaw-terminal-capture",
        )

    async def close(self) -> None:
        task = self._reader_task
        self._reader_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.mark_eof()
