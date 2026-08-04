# -*- coding: utf-8 -*-
"""Chrome plugin integration contracts grouped by runtime boundary."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import struct
import subprocess
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from plugins.bundle.chrome.assets.scripts import nm_host
from plugins.bundle.chrome.assets.scripts.handshake import (
    HandshakePermanentError,
    HandshakeTransientError,
)

# test_chrome_nm_frame_limits.py

_HOST_PATH = Path("plugins/bundle/chrome/assets/scripts/nm_host.py").resolve()


def _load_host() -> ModuleType:
    scripts = str(_HOST_PATH.parent)
    sys.path.insert(0, scripts)
    try:
        spec = importlib.util.spec_from_file_location(
            "nm_host_under_test",
            _HOST_PATH,
        )
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def test_two_mib_inbound_message_is_accepted() -> None:
    host = _load_host()
    payload = json.dumps(
        {"id": 1, "result": {"data": "x" * (2 * 1024 * 1024)}},
    )
    raw = payload.encode("utf-8")
    reader = io.BytesIO(struct.pack("<I", len(raw)) + raw)

    message = host.read_nm_message(reader)

    assert message["result"]["data"].startswith("x")
    assert len(message["result"]["data"]) == 2 * 1024 * 1024


def test_inbound_above_protocol_limit_is_rejected() -> None:
    host = _load_host()
    oversized = host.NM_MAX_INBOUND_BYTES + 1
    reader = io.BytesIO(struct.pack("<I", oversized))

    with pytest.raises(ValueError):
        host.read_nm_message(reader)


def test_oversized_outbound_message_writes_nothing() -> None:
    host = _load_host()
    stdout = io.BytesIO()

    with pytest.raises(host.NativeMessageTooLargeError):
        host.write_nm_message(
            stdout,
            {"id": 7, "result": "q" * 2_000_000},
        )

    assert stdout.getvalue() == b""


async def test_pump_reports_oversized_outbound_and_keeps_running() -> None:
    host = _load_host()

    class _Socket:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self._messages = [
                json.dumps({"id": 7, "result": "q" * 2_000_000}),
                json.dumps({"id": 8, "result": "ok"}),
            ]

        def __aiter__(self):
            return self._iterate()

        async def _iterate(self):
            for message in self._messages:
                yield message

        async def send(self, raw: str) -> None:
            self.sent.append(raw)

    socket, stdout = _Socket(), io.BytesIO()

    await host.pump_ws_to_stdout(socket, stdout)

    reported = [json.loads(item) for item in socket.sent]
    assert len(reported) == 1
    assert reported[0]["id"] == 7
    assert "error" in reported[0]
    assert b"ok" in stdout.getvalue()


# test_chrome_nm_host_fast_exit.py


def _config_path(tmp_path: Path) -> Path:
    path = tmp_path / "nm-bridge.json"
    path.write_text(
        json.dumps({"ws_url": "ws://bridge.test", "token": "token"}),
        encoding="utf-8",
    )
    return path


class _BlockingReader:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def read(self, _size: int) -> bytes:
        self.started.set()
        self.release.wait(timeout=5)
        return b""


class _ClosedWebSocket:
    def __init__(self, reader_started: threading.Event) -> None:
        self._reader_started = reader_started

    async def send(self, _message: str) -> None:
        return None

    async def close(self) -> None:
        return None

    def __aiter__(self) -> "_ClosedWebSocket":
        return self

    async def __anext__(self) -> str:
        await asyncio.to_thread(self._reader_started.wait)
        raise StopAsyncIteration


class _FailingSendWebSocket:
    def __init__(self) -> None:
        self._send_count = 0

    async def send(self, _message: str) -> None:
        self._send_count += 1
        if self._send_count == 1:
            return None
        raise RuntimeError("send failed")

    async def close(self) -> None:
        return None

    def __aiter__(self) -> "_FailingSendWebSocket":
        return self

    async def __anext__(self) -> str:
        await asyncio.Event().wait()
        raise StopAsyncIteration


def test_terminate_fires_while_stdin_read_is_still_blocked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reader = _BlockingReader()
    calls: list[tuple[int, bool]] = []

    async def connector(*_args: Any, **_kwargs: Any) -> _ClosedWebSocket:
        return _ClosedWebSocket(reader.started)

    async def acknowledge_hello(_ws: Any) -> dict[str, str]:
        return {"type": "hello_ack", "status": "ok"}

    def terminate(exit_code: int) -> None:
        calls.append((exit_code, reader.release.is_set()))
        reader.release.set()

    monkeypatch.setattr(nm_host, "wait_hello_ack", acknowledge_hello)

    asyncio.run(
        nm_host.run_bridge(
            _config_path(tmp_path),
            stdin=reader,
            stdout=io.BytesIO(),
            connector=connector,
            retry_seconds=0,
            terminate=terminate,
        ),
    )

    assert calls == [(0, False)]


def test_terminate_receives_1_when_a_pump_raises(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    calls: list[int] = []
    message = json.dumps({"method": "ping"}).encode("utf-8")
    stdin = io.BytesIO(len(message).to_bytes(4, "little") + message)

    async def connector(*_args: Any, **_kwargs: Any) -> _FailingSendWebSocket:
        return _FailingSendWebSocket()

    async def acknowledge_hello(_ws: Any) -> dict[str, str]:
        return {"type": "hello_ack", "status": "ok"}

    monkeypatch.setattr(nm_host, "wait_hello_ack", acknowledge_hello)

    asyncio.run(
        nm_host.run_bridge(
            _config_path(tmp_path),
            stdin=stdin,
            stdout=io.BytesIO(),
            connector=connector,
            retry_seconds=0,
            terminate=calls.append,
        ),
    )

    assert calls == [1]
    assert "send failed" in capsys.readouterr().err


# test_chrome_nm_host_handshake_e2e.py


class _CoreWebSocket:
    def __init__(self, response: str | Exception) -> None:
        self._response = response
        self.hello_messages: list[dict[str, Any]] = []
        self.closed = False

    async def send(self, raw: str) -> None:
        self.hello_messages.append(json.loads(raw))

    async def recv(self) -> str:
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    async def close(self) -> None:
        self.closed = True


def test_version_mismatch_stops_with_upgrade_advice(tmp_path: Path) -> None:
    websocket = _CoreWebSocket(
        json.dumps(
            {
                "type": "hello_ack",
                "status": "error",
                "code": "BROWSER_PROTOCOL_VERSION_MISMATCH",
                "expected_min_protocol_version": 2,
                "expected_protocol_version": 2,
                "actual_protocol_version": 1,
            },
        ),
    )

    async def connector(*_args: Any, **_kwargs: Any) -> _CoreWebSocket:
        return websocket

    with pytest.raises(HandshakePermanentError) as caught:
        asyncio.run(
            nm_host.run_bridge(
                _config_path(tmp_path),
                connector=connector,
                retry_seconds=1,
            ),
        )

    assert "upgrade the extension" in caught.value.advice
    assert websocket.closed
    assert websocket.hello_messages[0]["type"] == "hello"


def test_timeout_then_hello_ack_reaches_the_pipe_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _CoreWebSocket(asyncio.TimeoutError())
    second = _CoreWebSocket('{"type":"hello_ack","status":"ok"}')
    sockets = iter((first, second))
    entered_pump = False

    async def connector(*_args: Any, **_kwargs: Any) -> _CoreWebSocket:
        return next(sockets)

    async def enter_pump(*_args: Any) -> None:
        nonlocal entered_pump
        entered_pump = True

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(nm_host, "_run_single_backend_bridge", enter_pump)

    asyncio.run(
        nm_host.run_bridge(
            _config_path(tmp_path),
            connector=connector,
            retry_seconds=1,
            sleep=no_sleep,
        ),
    )

    assert first.closed
    assert second.hello_messages[0]["type"] == "hello"
    assert entered_pump


# test_chrome_nm_host_handshake_retry.py


class _WebSocket:
    async def send(self, _message: str) -> None:
        return None

    async def close(self) -> None:
        return None


def test_transient_hello_failure_reconnects_and_reenters_the_pump(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    entered_pump = False

    async def connector(*_args: Any, **_kwargs: Any) -> _WebSocket:
        nonlocal attempts
        attempts += 1
        return _WebSocket()

    async def acknowledge_hello(_ws: Any) -> dict[str, str]:
        if attempts == 1:
            raise HandshakeTransientError("Hello ack timeout")
        return {"type": "hello_ack", "status": "ok"}

    async def enter_pump(*_args: Any) -> None:
        nonlocal entered_pump
        entered_pump = True

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(nm_host, "wait_hello_ack", acknowledge_hello)
    monkeypatch.setattr(nm_host, "_run_single_backend_bridge", enter_pump)

    asyncio.run(
        nm_host.run_bridge(
            _config_path(tmp_path),
            connector=connector,
            retry_seconds=1,
            sleep=no_sleep,
        ),
    )

    assert attempts == 2
    assert entered_pump


# test_chrome_nm_host_keepalive_anchor.py

HOST = Path("plugins/bundle/chrome/assets/scripts/nm_host.py")
ACCEPTANCE = Path(".docs/ext-quick-fixes/manual-acceptance.md")


# test_chrome_nm_host_probe.py

HOST = Path("plugins/bundle/chrome/assets/scripts/nm_host.py")


def _frame(payload: dict) -> bytes:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def test_probe_echoes_one_frame_and_exits_zero() -> None:
    completed = subprocess.run(
        [sys.executable, str(HOST), "--probe"],
        input=_frame({"probe": "qwenpaw", "n": 1}),
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr.decode(
        "utf-8",
        "replace",
    )
    size = struct.unpack("<I", completed.stdout[:4])[0]
    echoed = json.loads(completed.stdout[4 : 4 + size].decode("utf-8"))
    assert echoed == {"probe": "qwenpaw", "n": 1}


# test_chrome_nm_host_single_backend.py

# pylint: disable=protected-access


SCRIPTS = Path("plugins/bundle/chrome/assets/scripts")


def _load_nm_host() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(
            "qwenpaw_chrome_nm_host",
            SCRIPTS / "nm_host.py",
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


class _BlockingInput:
    def __init__(self, initial: bytes) -> None:
        self._buffer = io.BytesIO(initial)
        self.release = threading.Event()

    def read(self, size: int = -1) -> bytes:
        value = self._buffer.read(size)
        if value:
            return value
        self.release.wait(timeout=2)
        return b""


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False
        self._incoming_yielded = asyncio.Event()

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self._messages()

    async def _messages(self):
        yield json.dumps({"direction": "core-to-extension"})
        self._incoming_yielded.set()
        await asyncio.Event().wait()


def _native_message(payload: dict[str, str]) -> bytes:
    encoded = json.dumps(payload).encode()
    return struct.pack("<I", len(encoded)) + encoded


def test_single_backend_bridge_pumps_both_directions() -> None:
    loaded_nm_host = _load_nm_host()
    stdin = _BlockingInput(_native_message({"direction": "extension-to-core"}))
    stdout = io.BytesIO()
    websocket = _FakeWebSocket()

    async def exercise() -> None:
        bridge = asyncio.create_task(
            loaded_nm_host._run_single_backend_bridge(
                stdin,
                stdout,
                websocket,
            ),
        )
        for _ in range(20):
            if websocket.sent and websocket._incoming_yielded.is_set():
                break
            await asyncio.sleep(0.01)
        stdin.release.set()
        await bridge

    asyncio.run(exercise())

    assert [json.loads(message) for message in websocket.sent] == [
        {"direction": "extension-to-core"},
    ]
    length = struct.unpack("<I", stdout.getvalue()[:4])[0]
    assert json.loads(stdout.getvalue()[4 : 4 + length]) == {
        "direction": "core-to-extension",
    }
    assert websocket.closed


# test_chrome_handshake_taxonomy.py


class _HelloWebSocket:
    def __init__(self, response: Any) -> None:
        self._response = response

    async def recv(self) -> Any:
        if self._response == "timeout":
            await asyncio.Event().wait()
        return self._response


# test_chrome_protocol_mirror.py

SCRIPTS = Path("plugins/bundle/chrome/assets/scripts")


def _load(name: str):
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(
            name,
            SCRIPTS / f"{name}.py",
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)
