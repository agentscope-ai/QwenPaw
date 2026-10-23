# -*- coding: utf-8 -*-
"""Canonical worker pipe framing, output separation and Windows I/O."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from qwenpaw.plugins.execution.bootstrap import (
    _ThreadPipeWriter,
    _open_protocol_transport,
)
from qwenpaw.plugins.execution.errors import (
    FrameClosedError,
    FrameLimitError,
    FrameTimeoutError,
    FrameWriteError,
)
from qwenpaw.plugins.execution.framing import (
    FramedTransport,
    FramingLimits,
    encode_frame,
)

FIXTURE_SOURCE_ROOT = (
    Path(__file__).parents[2] / "fixtures/channel_isolation/bootstrap_code"
)
PROTOCOL_OUTPUT_PROBE = FIXTURE_SOURCE_ROOT / "protocol_output_probe.py"


def _decode_frames(data: bytes) -> list[str]:
    """Decode complete frames emitted by FramedTransport."""
    messages: list[str] = []
    remaining = data
    while remaining:
        header, separator, body = remaining.partition(b"\r\n\r\n")
        assert separator
        name, value = header.split(b":", 1)
        assert name.lower() == b"content-length"
        length = int(value.strip())
        payload = body[:length]
        assert len(payload) == length
        messages.append(payload.decode("utf-8"))
        remaining = body[length:]
    return messages


def _read_pipe(fd: int, expected_bytes: int) -> bytes:
    """Drain an OS pipe until every expected frame byte arrives."""
    data = bytearray()
    try:
        while len(data) < expected_bytes:
            chunk = os.read(fd, expected_bytes - len(data))
            if not chunk:
                break
            data.extend(chunk)
    finally:
        os.close(fd)
    return bytes(data)


class _PartialWriteHandle:
    """Record bytes while accepting only a small prefix per write."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.closed = False

    def write(self, data: bytes) -> int:
        """Accept at most three bytes to exercise complete writes."""
        if self.closed:
            raise BrokenPipeError("handle is closed")
        accepted = min(3, len(data))
        self.data.extend(data[:accepted])
        return accepted

    def close(self) -> None:
        """Mark the fake handle closed."""
        self.closed = True


class _BrokenWriteHandle:
    """Fail every synchronous pipe write."""

    def write(self, _data: bytes) -> int:
        """Raise the OS error exposed by a closed peer."""
        raise BrokenPipeError("peer closed")

    def close(self) -> None:
        """Match the synchronous handle interface."""


class _BlockedWriteHandle:
    """Record whether cancellation prevents one blocked sync write."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.started = threading.Event()
        self.release = threading.Event()
        self.cancelled = False
        self.closed = False

    def write(self, data: bytes) -> int:
        """Wait for release, then either abort or record the write."""
        self.started.set()
        self.release.wait(timeout=1)
        if self.cancelled:
            raise OSError("synchronous write cancelled")
        self.data.extend(data)
        return len(data)

    def close(self) -> None:
        """Mark the fake protocol handle closed."""
        self.closed = True


class _LateSuccessfulWriteHandle:
    """Complete one blocked write even after cancellation was requested."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.started = threading.Event()
        self.release = threading.Event()
        self.closed = False

    def write(self, data: bytes) -> int:
        """Wait past the deadline, then accept the complete frame."""
        self.started.set()
        self.release.wait(timeout=1)
        self.data.extend(data)
        return len(data)

    def close(self) -> None:
        """Record closure without changing the in-flight write result."""
        self.closed = True


class _ChunkReadHandle:
    """Return one prepared stdin chunk followed by EOF."""

    def __init__(self, data: bytes) -> None:
        self._chunks = [data, b""]

    def read1(self, _: int) -> bytes:
        """Return the next prepared input chunk."""
        return self._chunks.pop(0)


class _FakeWindowsThreadHandle:
    """Cancel one fake synchronous write and record resource closure."""

    def __init__(
        self,
        protocol_handle: _BlockedWriteHandle | None = None,
        *,
        miss_first_cancel: bool = False,
    ) -> None:
        self._protocol_handle = protocol_handle
        self._miss_first_cancel = miss_first_cancel
        self.cancel_calls = 0
        self.closed = False

    def cancel(self) -> None:
        """Interrupt the fake write without permitting pending bytes."""
        self.cancel_calls += 1
        if self._miss_first_cancel and self.cancel_calls == 1:
            return
        if self._protocol_handle is not None:
            self._protocol_handle.cancelled = True
            self._protocol_handle.release.set()

    def close(self) -> None:
        """Record closure of the fake Win32 thread handle."""
        self.closed = True


def test_private_protocol_handle_emits_only_framed_output() -> None:
    """Production-order stdout isolation keeps frames and logs separate."""
    result = subprocess.run(
        [sys.executable, str(PROTOCOL_OUTPUT_PROBE)],
        cwd=FIXTURE_SOURCE_ROOT,
        capture_output=True,
        check=False,
        timeout=5,
    )

    assert result.returncode == 0
    assert _decode_frames(result.stdout) == ['{"probe":"ready"}']
    assert b"feishu-sdk-print" in result.stderr
    assert b"feishu-sdk-fd1" in result.stderr
    assert b"probe-print" in result.stderr
    assert b"probe-fd1" in result.stderr


@pytest.mark.asyncio
async def test_protocol_adapter_uses_framed_transport_single_writer() -> None:
    """Concurrent and large messages remain complete on the real pipe."""
    read_fd, write_fd = os.pipe()
    os.set_inheritable(write_fd, False)
    handle = os.fdopen(write_fd, "wb", buffering=0)
    transport = await _open_protocol_transport(FramedTransport, handle)
    messages = [f'{{"index":{index}}}' for index in range(16)]
    messages.append(json.dumps({"payload": "x" * (128 * 1024)}))
    expected_bytes = sum(len(encode_frame(value)) for value in messages)
    reader = asyncio.create_task(
        asyncio.to_thread(_read_pipe, read_fd, expected_bytes),
    )

    await asyncio.gather(*(transport.send(value) for value in messages))
    await transport.aclose()
    data = await reader

    assert _decode_frames(data) == messages


@pytest.mark.asyncio
async def test_windows_adapter_completes_partial_sync_writes() -> None:
    """The Windows path avoids Proactor and completes every sync write."""
    handle = _PartialWriteHandle()
    thread_handle = _FakeWindowsThreadHandle()
    transport = await _open_protocol_transport(
        FramedTransport,
        handle,
        platform_name="nt",
        writer_factory=lambda handle: _ThreadPipeWriter(
            handle,
            thread_handle_factory=lambda: thread_handle,
        ),
    )
    message = '{"platform":"windows"}'

    await transport.send(message)
    await transport.aclose()

    assert bytes(handle.data) == encode_frame(message)
    assert handle.closed
    assert thread_handle.closed


@pytest.mark.asyncio
async def test_windows_adapter_reads_runner_stdin() -> None:
    """The Windows thread reader feeds the trusted framed transport."""
    output = _PartialWriteHandle()
    thread_handle = _FakeWindowsThreadHandle()
    message = '{"platform":"windows-input"}'
    transport = await _open_protocol_transport(
        FramedTransport,
        output,
        platform_name="nt",
        writer_factory=lambda handle: _ThreadPipeWriter(
            handle,
            thread_handle_factory=lambda: thread_handle,
        ),
        input_handle=_ChunkReadHandle(encode_frame(message)),
    )

    assert await transport.receive() == message
    await transport.aclose()
    assert output.closed
    assert thread_handle.closed


@pytest.mark.asyncio
async def test_windows_adapter_preserves_framing_failures() -> None:
    """The Windows adapter retains broken-pipe and timeout semantics."""
    thread_handle = _FakeWindowsThreadHandle()
    broken = await _open_protocol_transport(
        FramedTransport,
        _BrokenWriteHandle(),
        platform_name="nt",
        writer_factory=lambda handle: _ThreadPipeWriter(
            handle,
            thread_handle_factory=lambda: thread_handle,
        ),
    )
    with pytest.raises(FrameWriteError):
        await broken.send("{}")
    await broken.aclose()
    assert thread_handle.closed


@pytest.mark.asyncio
async def test_windows_timeout_cancels_frame_and_closes_writer() -> None:
    """A timed-out frame cannot resume after transport shutdown."""
    blocked_handle = _BlockedWriteHandle()
    thread_handle = _FakeWindowsThreadHandle(
        blocked_handle,
        miss_first_cancel=True,
    )
    blocked = await _open_protocol_transport(
        FramedTransport,
        blocked_handle,
        platform_name="nt",
        writer_factory=lambda handle: _ThreadPipeWriter(
            handle,
            thread_handle_factory=lambda: thread_handle,
        ),
        limits=FramingLimits(write_timeout=0.05),
    )
    with pytest.raises(FrameTimeoutError):
        await blocked.send("{}")
    assert blocked_handle.started.wait(timeout=1)
    assert blocked.is_closed
    await blocked.aclose()

    assert thread_handle.cancel_calls >= 2
    assert thread_handle.closed
    assert blocked_handle.closed

    blocked_handle.release.set()
    await asyncio.sleep(0.01)

    assert blocked_handle.data == b""


@pytest.mark.asyncio
async def test_windows_late_success_preserves_timeout_and_closes_transport() -> None:
    """A late accepted HANDLE frame cannot turn a timeout into success."""
    handle = _LateSuccessfulWriteHandle()
    thread_handle = _FakeWindowsThreadHandle()
    transport = await _open_protocol_transport(
        FramedTransport,
        handle,
        platform_name="nt",
        writer_factory=lambda handle: _ThreadPipeWriter(
            handle,
            thread_handle_factory=lambda: thread_handle,
        ),
        limits=FramingLimits(write_timeout=0.02),
    )
    sending = asyncio.create_task(transport.send("{}"))
    assert await asyncio.to_thread(handle.started.wait, 1)

    with pytest.raises(FrameTimeoutError):
        await asyncio.wait_for(sending, timeout=0.2)
    assert transport.is_closed

    handle.release.set()
    while not handle.closed:
        await asyncio.sleep(0)

    assert bytes(handle.data) == encode_frame("{}")
    with pytest.raises(FrameClosedError):
        await transport.send("{}")
    await transport.aclose()
    assert thread_handle.closed


@pytest.mark.asyncio
async def test_protocol_adapter_reuses_framing_limits_and_failures() -> None:
    """Oversize, broken pipe, and write timeout keep CH-0-003 errors."""
    limited_read_fd, limited_write_fd = os.pipe()
    limited_handle = os.fdopen(limited_write_fd, "wb", buffering=0)
    limited = await _open_protocol_transport(
        FramedTransport,
        limited_handle,
        limits=FramingLimits(max_frame_bytes=8),
    )
    with pytest.raises(FrameLimitError):
        await limited.send("x" * 9)
    await limited.aclose()
    os.close(limited_read_fd)

    broken_read_fd, broken_write_fd = os.pipe()
    os.close(broken_read_fd)
    broken_handle = os.fdopen(broken_write_fd, "wb", buffering=0)
    broken = await _open_protocol_transport(
        FramedTransport,
        broken_handle,
    )
    with pytest.raises(FrameWriteError):
        await broken.send("{}")
    await broken.aclose()

    blocked_read_fd, blocked_write_fd = os.pipe()
    blocked_handle = os.fdopen(blocked_write_fd, "wb", buffering=0)
    blocked = await _open_protocol_transport(
        FramedTransport,
        blocked_handle,
        limits=FramingLimits(write_timeout=0.02),
    )
    with pytest.raises(FrameTimeoutError):
        await blocked.send("x" * (512 * 1024))
    assert blocked.is_closed
    await blocked.aclose()
    os.close(blocked_read_fd)
