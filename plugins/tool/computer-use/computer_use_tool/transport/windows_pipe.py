# -*- coding: utf-8 -*-
"""Windows named-pipe transport for the host-managed Computer Use helper."""

# The capability's endpoint name and secret are deliberately private so they
# cannot leak into tool inputs; a transport is their only intended reader.
# pylint: disable=protected-access

from __future__ import annotations

import asyncio
import contextvars
import ctypes
import json
import os
import struct
import threading
import time
from collections.abc import Callable, Mapping
from ctypes import wintypes
from typing import Any

from qwenpaw.app.computer_use.runtime import RuntimeCapability

from ..protocol import ComputerUseProtocolError, approval_reply
from .base import ComputerUseTransport, ReverseRequestHandler

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_FILE_FLAG_OVERLAPPED = 0x40000000
_ERROR_PIPE_BUSY = 231
_ERROR_FILE_NOT_FOUND = 2
_ERROR_IO_PENDING = 997
_WAIT_OBJECT_0 = 0x0
_WAIT_FAILED = 0xFFFFFFFF
_INFINITE = 0xFFFFFFFF
_MAX_FRAME_BYTES = 64 * 1024 * 1024
_CONNECT_TIMEOUT_SECONDS = 5
_WRITE_TIMEOUT_MS = 10000
_READ_POLL_MS = 500
_APPROVAL_POLL_SECONDS = 0.25
_CLOSE_JOIN_TIMEOUT_SECONDS = 2


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


class WindowsPipeTransport(ComputerUseTransport):
    """Length-prefixed JSON transport with native reverse-policy support."""

    def __init__(self, capability: RuntimeCapability) -> None:
        self._capability = capability
        self._handle: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._reader: threading.Thread | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._reverse_handler: ReverseRequestHandler | None = None
        self._reverse_context: contextvars.Context | None = None
        self._approvals_lock = threading.Lock()
        self._approvals_in_flight = 0
        self._closed = False

    async def connect(self) -> None:
        """Open the host-provided pipe and perform the protocol handshake."""
        if self._handle is not None:
            return
        if os.name != "nt":
            raise ComputerUseProtocolError(
                "runtime_unavailable",
                "Computer Use is only available on Windows.",
            )
        self._loop = asyncio.get_running_loop()
        self._handle = await asyncio.to_thread(_connect_pipe, self._pipe_path)
        self._reader = threading.Thread(
            target=self._reader_loop,
            name="computer-use-pipe-reader",
            daemon=True,
        )
        self._reader.start()
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
        if self._handle is None or self._closed:
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
        with self._pending_lock:
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
                    asyncio.to_thread(self._write_message, dict(message)),
                    timeout,
                )
            except Exception:
                # A failed or timed-out write may leave a partial frame on the
                # pipe, so the connection can no longer be trusted.
                future.cancel()
                await self.close()
                raise
            return await self._await_response(future, timeout)
        except TimeoutError as exc:
            raise ComputerUseProtocolError(
                "request_timeout",
                "Computer Use request timed out.",
            ) from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    async def _await_response(
        self,
        future: asyncio.Future[dict[str, Any]],
        timeout: float,
    ) -> dict[str, Any]:
        """Await a response without charging user approval time as timeout.

        The helper blocks serving a request while a reverse app approval
        waits for the user, so the machine deadline pauses until the
        approval resolves (bounded by the approval service's own timeout)
        and the helper then gets a fresh execution window.
        """
        deadline = time.monotonic() + timeout
        while True:
            with self._approvals_lock:
                approval_in_flight = self._approvals_in_flight > 0
            if approval_in_flight:
                deadline = time.monotonic() + timeout
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                future.cancel()
                raise TimeoutError
            try:
                return await asyncio.wait_for(
                    asyncio.shield(future),
                    min(remaining, _APPROVAL_POLL_SECONDS),
                )
            except TimeoutError:
                continue

    async def close(self) -> None:
        """Close the named pipe and reject every pending request."""
        if self._closed:
            return
        self._closed = True
        handle, self._handle = self._handle, None
        reader, self._reader = self._reader, None
        if handle is not None:
            await asyncio.to_thread(_close_handle, handle, reader)
        self._fail_pending(
            "runtime_disconnected",
            "Computer Use connection closed.",
        )

    def set_reverse_request_handler(
        self,
        handler: ReverseRequestHandler,
    ) -> None:
        self._reverse_handler = handler

    @property
    def _pipe_path(self) -> str:
        name = self._capability._pipe_name
        prefix = "\\\\.\\pipe\\"
        return name if name.startswith(prefix) else f"{prefix}{name}"

    def _write_message(self, message: dict[str, Any]) -> None:
        handle = self._handle
        if handle is None:
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
        with self._write_lock:
            _write_all(handle, struct.pack("<I", len(payload)) + payload)

    def _reader_loop(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            while not self._closed:
                message = _read_message(handle, lambda: self._closed)
                if message.get("method") == "request_app_approval":
                    self._schedule_reverse_request(message)
                else:
                    self._resolve_response(message)
        except Exception as exc:  # noqa: BLE001 - transport boundary
            if not self._closed:
                self._fail_pending(
                    "runtime_disconnected",
                    f"Computer Use connection failed: {exc}",
                )

    def _schedule_reverse_request(self, message: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None:
            return
        # Pause pending request deadlines while the user decides.
        with self._approvals_lock:
            self._approvals_in_flight += 1
        context = self._reverse_context
        if context is None:
            asyncio.run_coroutine_threadsafe(
                self._reply_to_reverse_request(message),
                loop,
            )
            return
        # run_coroutine_threadsafe would copy this reader thread's bare
        # context, losing the session contextvars, so schedule through
        # call_soon_threadsafe with the snapshot captured in request().
        loop.call_soon_threadsafe(
            self._start_reverse_task,
            message,
            context=context,
        )

    def _start_reverse_task(self, message: dict[str, Any]) -> None:
        asyncio.ensure_future(self._reply_to_reverse_request(message))

    async def _reply_to_reverse_request(self, message: dict[str, Any]) -> None:
        try:
            await self._handle_reverse_request(message)
        finally:
            with self._approvals_lock:
                self._approvals_in_flight -= 1

    async def _handle_reverse_request(self, message: dict[str, Any]) -> None:
        request_id = str(message.get("request_id") or "")
        handler = self._reverse_handler
        decision = {"allowed": False, "source": "invalid"}
        if request_id and handler is not None:
            try:
                decision = await handler(message)
            except Exception:  # noqa: BLE001 - fail closed at the pipe edge
                decision = {"allowed": False, "source": "error"}
        reply = approval_reply(
            request_id,
            allowed=bool(decision.get("allowed")),
            source=str(decision.get("source") or "unknown"),
        )
        try:
            await asyncio.to_thread(self._write_message, reply)
        except Exception:
            self._fail_pending(
                "runtime_disconnected",
                "Computer Use approval reply could not reach the native "
                "runtime.",
            )

    def _resolve_response(self, message: dict[str, Any]) -> None:
        request_id = str(message.get("request_id") or "")
        with self._pending_lock:
            future = self._pending.get(request_id)
        if future is None or future.done() or self._loop is None:
            return
        self._loop.call_soon_threadsafe(future.set_result, message)

    def _fail_pending(self, code: str, message: str) -> None:
        with self._pending_lock:
            futures = list(self._pending.values())
            self._pending.clear()
        for future in futures:
            if future.done() or self._loop is None:
                continue
            self._loop.call_soon_threadsafe(
                future.set_exception,
                ComputerUseProtocolError(code, message),
            )


def _connect_pipe(pipe_path: str) -> int:
    deadline = time.monotonic() + _CONNECT_TIMEOUT_SECONDS
    while True:
        handle = _kernel32().CreateFileW(
            pipe_path,
            _GENERIC_READ | _GENERIC_WRITE,
            0,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_OVERLAPPED,
            None,
        )
        if _valid_handle(handle):
            return int(handle)
        error = ctypes.get_last_error()
        remaining = deadline - time.monotonic()
        if (
            error in (_ERROR_PIPE_BUSY, _ERROR_FILE_NOT_FOUND)
            and remaining > 0
        ):
            if error == _ERROR_PIPE_BUSY:
                _kernel32().WaitNamedPipeW(
                    pipe_path,
                    max(1, min(250, int(remaining * 1000))),
                )
            else:
                time.sleep(min(0.05, remaining))
            continue
        if error == _ERROR_FILE_NOT_FOUND:
            raise ComputerUseProtocolError(
                "runtime_unavailable",
                "Computer Use native runtime is not running.",
            )
        raise OSError(
            error,
            f"Could not connect to Computer Use pipe {pipe_path!r}",
        )


def _read_message(
    handle: int,
    abort_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    frame_size = struct.unpack("<I", _read_exact(handle, 4, abort_check))[0]
    if not 0 < frame_size <= _MAX_FRAME_BYTES:
        raise ComputerUseProtocolError(
            "invalid_frame",
            "Invalid Computer Use frame size.",
        )
    value = json.loads(
        _read_exact(handle, frame_size, abort_check).decode("utf-8"),
    )
    if not isinstance(value, dict):
        raise ComputerUseProtocolError(
            "invalid_frame",
            "Invalid Computer Use message.",
        )
    return value


def _read_exact(
    handle: int,
    size: int,
    abort_check: Callable[[], bool] | None = None,
) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    event = _new_event()
    overlapped = _OVERLAPPED()
    overlapped.hEvent = event
    try:
        while remaining:
            if abort_check is not None and abort_check():
                raise OSError("Computer Use connection closed")
            buffer = ctypes.create_string_buffer(remaining)
            read = _run_io(
                handle,
                overlapped,
                lambda: _kernel32().ReadFile(
                    handle,
                    buffer,
                    remaining,
                    None,
                    ctypes.byref(overlapped),
                ),
                None,
                "Computer Use pipe read failed",
                abort_check,
            )
            if not read:
                raise OSError("Computer Use pipe closed")
            chunks.append(buffer.raw[:read])
            remaining -= read
    finally:
        _kernel32().CloseHandle(event)
    return b"".join(chunks)


def _write_all(handle: int, data: bytes) -> None:
    offset = 0
    event = _new_event()
    overlapped = _OVERLAPPED()
    overlapped.hEvent = event
    try:
        while offset < len(data):
            chunk = data[offset:]
            written = _run_io(
                handle,
                overlapped,
                lambda: _kernel32().WriteFile(
                    handle,
                    chunk,
                    len(chunk),
                    None,
                    ctypes.byref(overlapped),
                ),
                _WRITE_TIMEOUT_MS,
                "Computer Use pipe write failed",
            )
            if not written:
                raise OSError("Computer Use pipe closed")
            offset += written
    finally:
        _kernel32().CloseHandle(event)


def _run_io(
    handle: int,
    overlapped: _OVERLAPPED,
    start_io: Callable[[], bool],
    timeout_ms: int | None,
    error_message: str,
    abort_check: Callable[[], bool] | None = None,
) -> int:
    """Drive one overlapped ReadFile/WriteFile to completion.

    ``start_io`` issues the overlapped operation. Returns the number of bytes
    transferred. ``timeout_ms`` bounds the total wait. ``abort_check`` (read
    path) is polled every ``_READ_POLL_MS`` without touching the pending I/O,
    so a racing ``close()`` cannot strand the reader even when its
    ``CancelIoEx`` lands before the read was issued.
    """
    kernel32 = _kernel32()
    kernel32.ResetEvent(overlapped.hEvent)
    if not start_io():
        error = ctypes.get_last_error()
        if error != _ERROR_IO_PENDING:
            raise OSError(error, error_message)
        deadline = (
            None
            if timeout_ms is None
            else time.monotonic() + timeout_ms / 1000
        )
        while True:
            if abort_check is not None:
                wait_ms = _READ_POLL_MS
            elif deadline is None:
                wait_ms = _INFINITE
            else:
                wait_ms = max(1, int((deadline - time.monotonic()) * 1000))
            wait = kernel32.WaitForSingleObject(overlapped.hEvent, wait_ms)
            if wait == _WAIT_OBJECT_0:
                break
            if wait == _WAIT_FAILED:
                raise OSError(ctypes.get_last_error(), error_message)
            # WAIT_TIMEOUT: poll the abort flag / deadline; the I/O
            # stays pending and is only cancelled in the branches below.
            if abort_check is not None and abort_check():
                _cancel_and_drain(kernel32, handle, overlapped)
                raise OSError("Computer Use connection closed")
            if deadline is not None and time.monotonic() >= deadline:
                _cancel_and_drain(kernel32, handle, overlapped)
                raise TimeoutError("Computer Use pipe I/O timed out")
    transferred = wintypes.DWORD()
    if not kernel32.GetOverlappedResult(
        handle,
        ctypes.byref(overlapped),
        ctypes.byref(transferred),
        False,
    ):
        raise OSError(ctypes.get_last_error(), error_message)
    return transferred.value


def _cancel_and_drain(
    kernel32: Any,
    handle: int,
    overlapped: _OVERLAPPED,
) -> None:
    """Cancel and drain the pending operation before buffers are freed."""
    kernel32.CancelIoEx(handle, ctypes.byref(overlapped))
    drained = wintypes.DWORD()
    kernel32.GetOverlappedResult(
        handle,
        ctypes.byref(overlapped),
        ctypes.byref(drained),
        True,
    )


def _new_event() -> wintypes.HANDLE:
    event = _kernel32().CreateEventW(None, True, False, None)
    if not event:
        raise OSError(
            ctypes.get_last_error(),
            "Computer Use pipe event creation failed",
        )
    return event


def _close_handle(handle: int, reader: threading.Thread | None = None) -> None:
    """Cancel pending I/O, wait for the reader thread to unwind, then close."""
    _kernel32().CancelIoEx(handle, None)
    if (
        reader is not None
        and reader.is_alive()
        and reader is not threading.current_thread()
    ):
        reader.join(timeout=_CLOSE_JOIN_TIMEOUT_SECONDS)
        if reader.is_alive():
            # The reader did not unwind, so it may still be inside a call on
            # this handle. Closing now would let the kernel reuse the handle
            # value while that call is in flight, pointing it at whatever
            # object lands on the number next. Leaking one handle for the
            # life of the process is the safer trade.
            return
    _kernel32().CloseHandle(handle)


_kernel32_cache = None
_kernel32_cache_lock = threading.Lock()


def _kernel32():
    # The signatures are configured once and reused. Rebuilding the WinDLL
    # wrapper and re-declaring argtypes on every close/cancel/event call was
    # wasted work; the module itself was already loaded once by the OS.
    global _kernel32_cache
    if _kernel32_cache is None:
        with _kernel32_cache_lock:
            if _kernel32_cache is None:
                _kernel32_cache = _build_kernel32()
    return _kernel32_cache


def _build_kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    kernel32.WaitNamedPipeW.restype = wintypes.BOOL
    kernel32.CreateEventW.argtypes = [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateEventW.restype = wintypes.HANDLE
    kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
    kernel32.ResetEvent.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetOverlappedResult.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
    ]
    kernel32.GetOverlappedResult.restype = wintypes.BOOL
    kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
    kernel32.CancelIoEx.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def _valid_handle(handle: int | None) -> bool:
    return handle not in (None, 0, ctypes.c_void_p(-1).value)
