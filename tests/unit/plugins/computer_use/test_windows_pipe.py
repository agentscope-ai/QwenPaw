# -*- coding: utf-8 -*-
"""Regression tests for the overlapped Windows pipe transport.

Every test here deadlocks or hangs forever with the pre-fix synchronous pipe
handle, so they guard the overlapped I/O rework directly.
"""

# Nested helpers shadow the fixture name on purpose, and the fake handlers
# accept the arguments of the real signature without reading them all.
# pylint: disable=redefined-outer-name, unused-argument

from __future__ import annotations

import asyncio
import contextvars
import ctypes
import json
import os
import struct
import threading
import time
import uuid
from ctypes import wintypes
from typing import Any

import pytest

from computer_use_tool.protocol import ComputerUseProtocolError
from computer_use_tool.transport.windows_pipe import (
    WindowsPipeTransport,
    _kernel32,
)
from qwenpaw.app.computer_use.runtime import RuntimeCapability

pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="Windows named pipes only",
)

_PIPE_ACCESS_DUPLEX = 0x00000003
_PIPE_TYPE_BYTE = 0x00000000
_PIPE_WAIT = 0x00000000


class _MockHelper:
    """Minimal in-process stand-in for the native computer-use helper."""

    def __init__(self) -> None:
        suffix = uuid.uuid4().hex[:8]
        self.pipe_name = f"qwenpaw-cu-test-{os.getpid()}-{suffix}"
        self.secret = "test-secret"
        self.stop_reading = threading.Event()
        self._ready = threading.Event()

    def start(self) -> None:
        thread = threading.Thread(
            target=self._serve,
            name="mock-helper",
            daemon=True,
        )
        thread.start()
        assert self._ready.wait(5), "mock helper pipe did not appear"

    def _serve(self) -> None:
        kernel32 = _kernel32()
        kernel32.CreateNamedPipeW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
        ]
        kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
        kernel32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
        kernel32.ConnectNamedPipe.restype = wintypes.BOOL
        kernel32.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
        kernel32.DisconnectNamedPipe.restype = wintypes.BOOL
        path = f"\\\\.\\pipe\\{self.pipe_name}"
        while True:
            hpipe = kernel32.CreateNamedPipeW(
                path,
                _PIPE_ACCESS_DUPLEX,
                _PIPE_TYPE_BYTE | _PIPE_WAIT,
                1,
                65536,
                4096,
                0,
                None,
            )
            self._ready.set()
            kernel32.ConnectNamedPipe(hpipe, None)
            try:
                self._serve_connection(kernel32, hpipe)
            finally:
                kernel32.DisconnectNamedPipe(hpipe)
                kernel32.CloseHandle(hpipe)

    def _serve_connection(self, kernel32, hpipe) -> None:
        while True:
            header = self._read_fully(kernel32, hpipe, 4)
            if header is None:
                return
            size = struct.unpack("<I", header)[0]
            body = self._read_fully(kernel32, hpipe, size)
            if body is None:
                return
            message = json.loads(body.decode("utf-8"))
            method = message.get("method")
            request_id = message.get("request_id")
            result: dict[str, Any]
            if method == "hello":
                result = {"protocol_version": 1}
            elif method == "list_apps":
                result = {"apps": []}
            elif method == "delayed":
                time.sleep(0.1)
                result = {"done": True}
            elif method == "no_reply":
                continue
            elif method == "needs_approval":
                reverse = {
                    "request_id": f"approval-{request_id}",
                    "method": "request_app_approval",
                    "params": {
                        "canonical_app_id": "process:test.exe",
                        "display_name": "Test App",
                        "identity_evidence": {},
                        "risk": "low",
                        "warning": "",
                    },
                    "meta": message.get("meta"),
                    "protocol_version": 1,
                }
                self._write_frame(kernel32, hpipe, reverse)
                reply = self._read_message(kernel32, hpipe)
                if reply is None:
                    return
                decision = (reply.get("result") or {}).get("decision")
                result = {"approved": decision == "allow"}
            elif method == "stop_reading":
                self._reply(kernel32, hpipe, request_id, {"stopped": True})
                self.stop_reading.set()
                while self.stop_reading.is_set():
                    time.sleep(0.05)
                return  # client is gone by now
            else:
                continue
            self._reply(kernel32, hpipe, request_id, result)

    def _read_message(self, kernel32, hpipe) -> dict | None:
        header = self._read_fully(kernel32, hpipe, 4)
        if header is None:
            return None
        body = self._read_fully(
            kernel32,
            hpipe,
            struct.unpack("<I", header)[0],
        )
        if body is None:
            return None
        return json.loads(body.decode("utf-8"))

    @staticmethod
    def _read_fully(kernel32, hpipe, size: int) -> bytes | None:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            buffer = ctypes.create_string_buffer(remaining)
            read = wintypes.DWORD()
            ok = kernel32.ReadFile(
                hpipe,
                buffer,
                remaining,
                ctypes.byref(read),
                None,
            )
            if not ok or not read.value:
                return None
            chunks.append(buffer.raw[: read.value])
            remaining -= read.value
        return b"".join(chunks)

    def _reply(self, kernel32, hpipe, request_id, result: dict) -> None:
        self._write_frame(
            kernel32,
            hpipe,
            {"request_id": request_id, "ok": True, "result": result},
        )

    @staticmethod
    def _write_frame(kernel32, hpipe, message: dict) -> None:
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        data = struct.pack("<I", len(payload)) + payload
        written = wintypes.DWORD()
        kernel32.WriteFile(hpipe, data, len(data), ctypes.byref(written), None)


@pytest.fixture()
def mock_helper():
    helper = _MockHelper()
    helper.start()
    yield helper
    helper.stop_reading.clear()


def _request(
    method: str,
    params: dict | None = None,
    deadline: int = 10000,
) -> dict:
    return {
        "request_id": uuid.uuid4().hex,
        "method": method,
        "params": params or {},
        "meta": {
            "session_id": "test",
            "turn_id": "test",
            "deadline_ms": deadline,
        },
        "protocol_version": 1,
    }


def _transport(helper: _MockHelper) -> WindowsPipeTransport:
    capability = RuntimeCapability(helper.pipe_name, helper.secret, 1)
    return WindowsPipeTransport(capability)


_session_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "cu_test_session",
    default="",
)


def test_reverse_request_inherits_request_context(
    mock_helper: _MockHelper,
) -> None:
    """The approval coroutine must see the requesting task's contextvars.

    Before the fix, run_coroutine_threadsafe copied the reader thread's
    bare context, so session contextvars were lost and every reverse
    approval was denied with source=session_mismatch.
    """
    seen: list[str] = []

    async def handler(message: dict) -> dict:
        seen.append(_session_var.get())
        return {"allowed": True, "source": "session"}

    async def run() -> None:
        transport = _transport(mock_helper)
        transport.set_reverse_request_handler(handler)
        await asyncio.wait_for(transport.connect(), 5)
        _session_var.set("session-ctx")
        response = await transport.request(_request("needs_approval"))
        assert response.get("ok")
        assert response.get("result", {}).get("approved") is True
        await transport.close()

    asyncio.run(run())
    assert seen == ["session-ctx"]


def test_slow_approval_pauses_request_deadline(
    mock_helper: _MockHelper,
) -> None:
    """Waiting for the user's approval must not consume the deadline.

    The helper blocks serving the request until the approval reply, so
    a user slower than deadline_ms used to fail it with request_timeout
    before the approval could ever be granted.
    """

    async def handler(message: dict) -> dict:
        await asyncio.sleep(2.0)  # user is slower than the 1s deadline
        return {"allowed": True, "source": "session"}

    async def run() -> None:
        transport = _transport(mock_helper)
        transport.set_reverse_request_handler(handler)
        await asyncio.wait_for(transport.connect(), 5)
        response = await transport.request(
            _request("needs_approval", deadline=1000),
        )
        assert response.get("ok")
        assert response.get("result", {}).get("approved") is True
        await transport.close()

    asyncio.run(run())


def test_connect_handshake_does_not_deadlock(mock_helper: _MockHelper) -> None:
    async def run() -> None:
        transport = _transport(mock_helper)
        await asyncio.wait_for(transport.connect(), 5)
        response = await transport.request(_request("list_apps"))
        assert response.get("ok")
        await transport.close()

    asyncio.run(run())


def test_concurrent_requests_while_reader_parked(
    mock_helper: _MockHelper,
) -> None:
    async def run() -> None:
        transport = _transport(mock_helper)
        await asyncio.wait_for(transport.connect(), 5)
        requests = [transport.request(_request("delayed")) for _ in range(5)]
        responses = await asyncio.gather(*requests)
        assert all(response.get("ok") for response in responses)
        await transport.close()

    asyncio.run(run())


def test_response_timeout_keeps_connection(mock_helper: _MockHelper) -> None:
    async def run() -> None:
        transport = _transport(mock_helper)
        await asyncio.wait_for(transport.connect(), 5)
        with pytest.raises(ComputerUseProtocolError, match="timed out"):
            await transport.request(_request("no_reply", deadline=1000))
        response = await transport.request(_request("list_apps"))
        assert response.get("ok")
        await transport.close()

    asyncio.run(run())


def test_close_cancels_parked_reader(mock_helper: _MockHelper) -> None:
    async def run() -> None:
        transport = _transport(mock_helper)
        await asyncio.wait_for(transport.connect(), 5)
        # The reader thread is parked in ReadFile; close must stay fast.
        start = time.monotonic()
        await transport.close()
        assert time.monotonic() - start < 2
        with pytest.raises(ComputerUseProtocolError):
            await transport.request(_request("list_apps"))

    asyncio.run(run())


def test_write_timeout_closes_connection(mock_helper: _MockHelper) -> None:
    async def run() -> None:
        transport = _transport(mock_helper)
        await asyncio.wait_for(transport.connect(), 5)
        response = await transport.request(_request("stop_reading"))
        assert response.get("ok")
        # The helper never drains the pipe, so this frame exceeds the
        # buffer and the write stalls until _WRITE_TIMEOUT_MS kicks in.
        big = _request(
            "list_apps",
            params={"blob": "x" * 1_000_000},
            deadline=30000,
        )
        start = time.monotonic()
        with pytest.raises(ComputerUseProtocolError, match="timed out"):
            await transport.request(big)
        assert time.monotonic() - start < 20
        # A partial frame may be on the wire: the connection must be poisoned.
        with pytest.raises(ComputerUseProtocolError):
            await transport.request(_request("list_apps"))

    asyncio.run(run())
