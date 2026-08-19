#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Single-backend Native Messaging dumb pipe for QwenPaw."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, BinaryIO, Callable

try:
    from .handshake import (
        HandshakePermanentError,
        send_hello,
        wait_hello_ack,
    )
except ImportError:
    from handshake import HandshakePermanentError, send_hello, wait_hello_ack

try:
    from .protocol_mirror import (
        NM_CLOSE_FRAME_PROTOCOL,
        NM_CLOSE_INBOUND_TOO_LARGE,
        NM_CLOSE_INTERNAL_ERROR,
        NM_CLOSE_STDIN_EOF,
        NM_MAX_INBOUND_BYTES,
        NM_MAX_OUTBOUND_BYTES,
        close_code_catalog,
    )
except ImportError:
    from protocol_mirror import (
        NM_CLOSE_FRAME_PROTOCOL,
        NM_CLOSE_INBOUND_TOO_LARGE,
        NM_CLOSE_INTERNAL_ERROR,
        NM_CLOSE_STDIN_EOF,
        NM_MAX_INBOUND_BYTES,
        NM_MAX_OUTBOUND_BYTES,
        close_code_catalog,
    )

DEFAULT_CONFIG_PATH = Path.home() / ".qwenpaw" / "nm-bridge.json"
DEFAULT_CONNECT_RETRY_SECONDS = 120.0
INITIAL_CONNECT_RETRY_DELAY_SECONDS = 0.5
MAX_CONNECT_RETRY_DELAY_SECONDS = 5.0
LOG_PATH = Path.home() / ".qwenpaw" / "logs" / "nm-host.log"
LOG_MAX_BYTES = 8 * 1024 * 1024
_DRAIN_CHUNK_BYTES = 64 * 1024
_ID_RE = re.compile(rb'"id"\s*:\s*("(?:[^"\\]|\\.)*"|-?\d+)')
# Chrome Native Messaging limits are imported from protocol_mirror. They are
# protocol facts, not tunables: Chrome kills this process above its hard wall.


class InvalidTokenError(ValueError):
    """Raised when Native Messaging configuration has no bearer token."""


class NativeMessageTooLargeError(ValueError):
    """Raised when a core message exceeds Chrome's host-to-extension limit."""


class InboundFrameTooLargeError(ValueError):
    """Raised after an oversized inbound frame has been drained."""

    def __init__(self, size: int, head: bytes) -> None:
        super().__init__("Native Messaging frame exceeds maximum size")
        self.size = size
        self.head = head


def _dumps(message: dict[str, Any]) -> str:
    return json.dumps(message, separators=(",", ":"))


def log_diagnostic(text: str) -> None:
    """Persist a flushed diagnostic line without changing bridge behavior."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_MAX_BYTES:
            previous = LOG_PATH.with_suffix(".log.1")
            if previous.exists():
                previous.unlink()
            LOG_PATH.replace(previous)
        timestamp = datetime.now(timezone.utc).isoformat()
        with LOG_PATH.open("a", encoding="utf-8") as output:
            output.write(f"{timestamp} {text}\n")
            output.flush()
    except OSError:
        # Chrome controls stderr's destination; an unavailable local log must
        # not turn a recoverable bridge error into a different failure.
        return


def _drain(reader: BinaryIO, size: int, keep_first: int = 4096) -> bytes:
    """Discard a frame in bounded reads while preserving a diagnostic head."""
    remaining = size
    head_parts: list[bytes] = []
    kept = 0
    while remaining > 0:
        chunk = reader.read(min(_DRAIN_CHUNK_BYTES, remaining))
        if not chunk:
            break
        remaining -= len(chunk)
        if kept < keep_first:
            fragment = chunk[: keep_first - kept]
            head_parts.append(fragment)
            kept += len(fragment)
    return b"".join(head_parts)


def _close_reason(text: str) -> str:
    """Fit a WebSocket close reason into its 123-byte UTF-8 limit."""
    encoded = text.encode("utf-8")[:123]
    while encoded:
        try:
            return encoded.decode("utf-8")
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    return ""


def read_nm_frame(reader: BinaryIO) -> bytes | None:
    """Read one length-prefixed Native Messaging frame as raw bytes."""
    raw_length = reader.read(4)
    if not raw_length:
        return None
    if len(raw_length) != 4:
        raise EOFError("Incomplete Native Messaging length prefix")
    size = struct.unpack("<I", raw_length)[0]
    if size > NM_MAX_INBOUND_BYTES:
        raise InboundFrameTooLargeError(size, _drain(reader, size))
    payload = reader.read(size)
    if len(payload) != size:
        raise EOFError("Incomplete Native Messaging payload")
    return payload


def write_nm_frame(writer: BinaryIO, payload: bytes) -> None:
    """Write one length-prefixed frame; enforce Chrome's outbound wall."""
    if len(payload) > NM_MAX_OUTBOUND_BYTES:
        raise NativeMessageTooLargeError(
            f"core message is {len(payload)} bytes, above Chrome's "
            f"{NM_MAX_OUTBOUND_BYTES}-byte host-to-extension limit",
        )
    writer.write(struct.pack("<I", len(payload)) + payload)
    writer.flush()


def _set_binary_stdio() -> None:
    """Prevent Windows text-mode newline conversion from corrupting frames."""
    if sys.platform != "win32":
        return
    import msvcrt

    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)


def run_probe(
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
) -> int:
    """Echo one frame without loading config or third-party runtime."""
    payload = read_nm_frame(stdin or sys.stdin.buffer)
    if payload is not None:
        write_nm_frame(stdout or sys.stdout.buffer, payload)
    return 0


def _load_websockets() -> Any:
    """Import the runtime dependency through one testable boundary."""
    import websockets

    return websockets


def validate_runtime() -> None:
    """Reject a missing or API-incompatible WebSocket runtime."""
    websockets = _load_websockets()
    connect = getattr(websockets, "connect", None)
    if not callable(connect):
        raise RuntimeError("websockets.connect is unavailable")
    try:
        parameters = inspect.signature(connect).parameters
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "websockets.connect has an unreadable signature",
        ) from exc
    if "additional_headers" not in parameters:
        version = str(getattr(websockets, "__version__", "unknown"))
        raise RuntimeError(
            f"incompatible websockets {version}: connect() must support "
            "additional_headers",
        )


def run_runtime_check() -> int:
    """Check third-party runtime APIs without reading bridge state."""
    try:
        validate_runtime()
    except Exception as exc:
        diagnostic = (
            "Native Messaging host runtime check failed: "
            f"{type(exc).__name__}: {exc}"
        )
        print(diagnostic, file=sys.stderr)
        return 1
    return 0


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, str]:
    """Load the one configured core backend and its bearer token."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    ws_url = str(data.get("ws_url") or "").strip()
    token = str(data.get("token") or "").strip()
    if not ws_url:
        raise ValueError("Native Messaging bridge ws_url is required")
    if not token:
        raise InvalidTokenError("Native Messaging bridge token is required")
    return {"ws_url": ws_url, "token": token}


async def connect_websocket(
    url: str,
    token: str,
    connector: Callable[..., Any] | None = None,
) -> Any:
    """Connect the pipe to its only backend."""
    token = token.strip()
    if not token:
        raise InvalidTokenError("Native Messaging bridge token is required")
    headers = {"Authorization": f"Bearer {token}"}
    if connector:
        return await connector(
            url,
            additional_headers=headers,
            max_size=NM_MAX_OUTBOUND_BYTES,
        )
    websockets = _load_websockets()

    # Fast exit relies on websockets' default ping/pong keepalive (20-second
    # interval and timeout) to end iteration on a half-open peer; never disable
    # ping_interval here or the zombie Native Messaging host bug returns.
    # Frames destined for the extension cannot exceed Chrome's hard outbound
    # wall, so accepting more would only defer the inevitable host failure.
    return await websockets.connect(
        url,
        additional_headers=headers,
        max_size=NM_MAX_OUTBOUND_BYTES,
    )


async def connect_websocket_with_retry(
    url: str,
    token: str,
    connector: Callable[..., Any] | None = None,
    on_connected: Callable[[Any], Awaitable[None]] | None = None,
    *,
    retry_seconds: float = DEFAULT_CONNECT_RETRY_SECONDS,
    sleep: Callable[[float], Any] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Any:
    """Connect and initialize the bridge through a short core restart."""
    if retry_seconds <= 0:
        ws = await connect_websocket(url, token, connector)
        if on_connected is not None:
            await on_connected(ws)
        return ws

    deadline = monotonic() + retry_seconds
    delay = INITIAL_CONNECT_RETRY_DELAY_SECONDS
    while True:
        ws = None
        try:
            ws = await connect_websocket(url, token, connector)
            if on_connected is not None:
                await on_connected(ws)
            return ws
        except HandshakePermanentError:
            if ws is not None:
                await ws.close()
            raise
        except Exception:
            if ws is not None:
                await ws.close()
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise
            wait_seconds = min(delay, remaining)
            result = sleep(wait_seconds)
            if asyncio.iscoroutine(result):
                await result
            delay = min(delay * 2, MAX_CONNECT_RETRY_DELAY_SECONDS)


async def pump_stdin_to_ws(stdin: BinaryIO, ws: Any) -> None:
    """Pump extension messages straight to the configured core backend."""
    while True:
        try:
            payload = await asyncio.to_thread(read_nm_frame, stdin)
        except InboundFrameTooLargeError as exc:
            match = _ID_RE.search(exc.head)
            try:
                message_id = json.loads(match.group(1)) if match else None
            except (TypeError, json.JSONDecodeError):
                message_id = None
            log_diagnostic(
                "Rejected oversized inbound Native Messaging frame "
                f"size={exc.size}",
            )
            await ws.send(
                _dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": message_id,
                        "error": {
                            "code": -32002,
                            "message": (
                                "Native Messaging frame exceeds maximum "
                                f"size ({exc.size} bytes)"
                            ),
                        },
                    },
                ),
            )
            continue
        if payload is None:
            return
        await ws.send(payload.decode("utf-8"))


async def pump_ws_to_stdout(ws: Any, stdout: BinaryIO) -> None:
    """Pump core backend messages straight back to the extension."""
    async for raw_message in ws:
        payload = (
            raw_message
            if isinstance(raw_message, bytes)
            else raw_message.encode("utf-8")
        )
        try:
            await asyncio.to_thread(write_nm_frame, stdout, payload)
        except NativeMessageTooLargeError as exc:
            # Unreachable in production: websocket max_size equals the
            # Chrome wall and pass-through never changes byte counts.
            diagnostic = f"Rejecting oversized core message: {exc}"
            print(diagnostic, file=sys.stderr)
            log_diagnostic(diagnostic)
            message_id = None
            try:
                message_id = json.loads(payload).get("id")
            except Exception:
                pass
            await ws.send(
                _dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": message_id,
                        "error": {"code": -32001, "message": str(exc)},
                    },
                ),
            )
            continue


async def _run_single_backend_bridge(
    stdin: BinaryIO,
    stdout: BinaryIO,
    ws: Any,
) -> None:
    """Run the two direct pump loops until either side disconnects."""
    tasks = {
        asyncio.create_task(pump_stdin_to_ws(stdin, ws)),
        asyncio.create_task(pump_ws_to_stdout(ws, stdout)),
    }
    close_code = NM_CLOSE_STDIN_EOF
    close_reason = close_code_catalog()[close_code]
    try:
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()
    except EOFError as exc:
        if "length prefix" in str(exc).lower():
            close_code = NM_CLOSE_FRAME_PROTOCOL
        else:
            close_code = NM_CLOSE_INTERNAL_ERROR
        close_reason = str(exc)
        raise
    except InboundFrameTooLargeError as exc:
        close_code = NM_CLOSE_INBOUND_TOO_LARGE
        close_reason = str(exc)
        raise
    except Exception as exc:
        close_code = NM_CLOSE_INTERNAL_ERROR
        close_reason = str(exc)
        raise
    finally:
        log_diagnostic(
            "Native Messaging bridge closed "
            f"code={close_code} reason={close_reason}",
        )
        await ws.close(code=close_code, reason=_close_reason(close_reason))


async def run_bridge(
    config_path: Path = DEFAULT_CONFIG_PATH,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
    *,
    connector: Callable[..., Any] | None = None,
    retry_seconds: float = DEFAULT_CONNECT_RETRY_SECONDS,
    sleep: Callable[[float], Any] = asyncio.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    terminate: Callable[[int], None] | None = None,
) -> None:
    """Connect, handshake, then run the direct Native Messaging pipe."""
    config = load_config(config_path)

    async def send_and_wait_for_hello(ws: Any) -> None:
        await send_hello(ws, "")
        await wait_hello_ack(ws)

    ws = await connect_websocket_with_retry(
        config["ws_url"],
        config["token"],
        connector,
        send_and_wait_for_hello,
        retry_seconds=retry_seconds,
        sleep=sleep,
        monotonic=monotonic,
    )
    try:
        await _run_single_backend_bridge(
            stdin or sys.stdin.buffer,
            stdout or sys.stdout.buffer,
            ws,
        )
    except Exception as exc:
        if terminate is None:
            raise
        diagnostic = f"Native Messaging bridge pump failed: {exc}"
        print(diagnostic, file=sys.stderr)
        log_diagnostic(diagnostic)
        exit_code = 1
    else:
        exit_code = 0

    if terminate is not None:
        sys.stdout.buffer.flush()
        sys.stderr.flush()
        terminate(exit_code)


def main() -> int:
    """Run the Native Messaging host."""
    _set_binary_stdio()
    if sys.argv[1:] == ["--probe"]:
        return run_probe()
    if sys.argv[1:] == ["--check-runtime"]:
        return run_runtime_check()
    try:
        validate_runtime()
        asyncio.run(run_bridge(terminate=os._exit))
    except HandshakePermanentError as exc:
        diagnostic = exc.advice or str(exc)
        print(diagnostic, file=sys.stderr)
        log_diagnostic(diagnostic)
        return 1
    except Exception as exc:
        diagnostic = (
            "Native Messaging host startup failed: "
            f"{type(exc).__name__}: {exc}"
        )
        print(diagnostic, file=sys.stderr)
        log_diagnostic(diagnostic)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
