"""Tests for the thin Computer Use protocol adapter."""

from __future__ import annotations

from collections.abc import Mapping
import json
import socket
import threading
from typing import Any

import pytest

import computer_use_tool.client as client_module
from computer_use_tool.client import ComputerUseClient
from computer_use_tool.dispatch import (
    _dialog_hint,
    _native_request,
    _note_new_windows,
    _response,
)
from computer_use_tool.transport.base import ComputerUseTransport, ReverseRequestHandler
from qwenpaw.app.computer_use import (
    HostRuntimeProvider,
    set_current_computer_use_turn_id,
)
from qwenpaw.app.computer_use import runtime as runtime_module


@pytest.fixture(autouse=True)
def _reset_host_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "QWENPAW_COMPUTER_USE_PIPE",
        "QWENPAW_COMPUTER_USE_CAPABILITY",
        "QWENPAW_COMPUTER_USE_PROTOCOL",
        "QWENPAW_COMPUTER_USE_CONTROL_HOST",
        "QWENPAW_COMPUTER_USE_CONTROL_PORT",
        "QWENPAW_COMPUTER_USE_CONTROL_TOKEN",
        "QWENPAW_COMPUTER_USE_CONTROL_PROTOCOL",
    ):
        monkeypatch.delenv(name, raising=False)
    HostRuntimeProvider._capability = None
    yield
    HostRuntimeProvider._capability = None


def test_host_runtime_requests_a_capability_only_when_needed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    token = "test-token"
    received: dict[str, object] = {}

    def _serve_once() -> None:
        with listener:
            connection, _ = listener.accept()
            with connection, connection.makefile("rwb") as stream:
                received.update(json.loads(stream.readline()))
                stream.write(
                    b'{"ok":true,"pipe_name":"pipe-1","capability":"secret-1",'
                    b'"protocol_version":1}\n'
                )
                stream.flush()

    server = threading.Thread(target=_serve_once)
    server.start()
    monkeypatch.setenv("QWENPAW_COMPUTER_USE_CONTROL_HOST", "127.0.0.1")
    monkeypatch.setenv("QWENPAW_COMPUTER_USE_CONTROL_PORT", str(port))
    monkeypatch.setenv("QWENPAW_COMPUTER_USE_CONTROL_TOKEN", token)
    monkeypatch.setenv("QWENPAW_COMPUTER_USE_CONTROL_PROTOCOL", "1")

    assert HostRuntimeProvider.is_available() is True
    assert received == {}
    capability = HostRuntimeProvider.acquire_capability()
    server.join(timeout=1)

    assert capability == runtime_module.RuntimeCapability("pipe-1", "secret-1", 1)
    assert received == {
        "protocol_version": 1,
        "token": token,
        "action": "acquire",
    }


def test_coordinate_input_requires_one_complete_visual_snapshot() -> None:
    method, params, include_images = _native_request(
        "click",
        window_id="123",
        snapshot_id="snapshot-1",
        screenshot_id="screenshot-1",
        x=40,
        y=60,
        button="left",
        count=1,
    )

    assert method == "click"
    assert include_images is False
    assert params == {
        "window_id": "123",
        "snapshot_id": "snapshot-1",
        "screenshot_id": "screenshot-1",
        "x": 40,
        "y": 60,
        "button": "left",
        "count": 1,
    }


def test_coordinate_input_rejects_missing_snapshot_identifier() -> None:
    with pytest.raises(ValueError, match="snapshot_id"):
        _native_request(
            "click",
            window_id="123",
            snapshot_id="",
            screenshot_id="screenshot-1",
            x=40,
            y=60,
            button="left",
            count=1,
        )


def test_screenshot_data_stays_out_of_the_text_block() -> None:
    """Inline screenshot data must not be duplicated into the JSON text."""
    data_url = "data:image/jpeg;base64," + "A" * 4096
    payload = {
        "ok": True,
        "screenshots": [
            {
                "id": "screenshot-1",
                "url": data_url,
                "width": 800,
                "height": 600,
            },
        ],
    }

    response = _response(payload, include_images=True)

    image_blocks = [
        block for block in response.content if block.type == "data"
    ]
    text_blocks = [
        block for block in response.content if block.type == "text"
    ]
    assert len(image_blocks) == 1
    assert str(image_blocks[0].source.url) == data_url
    assert len(text_blocks) == 1
    assert data_url not in text_blocks[0].text
    assert "screenshot-1" in text_blocks[0].text


def test_uia_input_keeps_its_own_revision_and_element() -> None:
    method, params, _ = _native_request(
        "invoke",
        window_id="123",
        accessibility_revision="accessibility-1",
        element_id="uia-7",
    )

    assert method == "invoke_element"
    assert params == {
        "window_id": "123",
        "accessibility_revision": "accessibility-1",
        "element_id": "uia-7",
    }


class _FakeTransport(ComputerUseTransport):
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.handler: ReverseRequestHandler | None = None
        self.closed = False

    async def connect(self) -> None:
        return None

    async def request(self, message: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(message)
        self.messages.append(payload)
        if payload["method"] == "hello":
            return {
                "request_id": payload["request_id"],
                "ok": True,
                "result": {"protocol_version": 1},
            }
        return {"request_id": payload["request_id"], "ok": True, "result": {}}

    async def close(self) -> None:
        self.closed = True

    def set_reverse_request_handler(self, handler: ReverseRequestHandler) -> None:
        self.handler = handler


@pytest.mark.asyncio
async def test_client_binds_session_and_turn_to_native_request() -> None:
    transport = _FakeTransport()
    client = ComputerUseClient("session-1", lambda: transport)
    set_current_computer_use_turn_id("turn-1")
    try:
        await client.execute("list_windows", {})
    finally:
        set_current_computer_use_turn_id(None)

    request = transport.messages[-1]
    assert request["method"] == "list_windows"
    assert request["meta"] == {
        "session_id": "session-1",
        "turn_id": "turn-1",
        "deadline_ms": 10000,
    }


@pytest.mark.asyncio
async def test_acquire_capability_retries_cold_start_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient acquire miss must be retried before giving up."""
    attempts: list[int] = []
    capability = runtime_module.RuntimeCapability("pipe-1", "secret-1", 1)

    def _flaky_acquire():
        attempts.append(len(attempts))
        return None if len(attempts) < 3 else capability

    monkeypatch.setattr(
        client_module.HostRuntimeProvider,
        "acquire_capability",
        _flaky_acquire,
    )
    monkeypatch.setattr(client_module, "_ACQUIRE_RETRY_DELAY_SECONDS", 0.0)

    acquired = await ComputerUseClient._acquire_capability()

    assert acquired == capability
    assert len(attempts) == 3


@pytest.mark.asyncio
async def test_acquire_capability_gives_up_after_bounded_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persistent failures must surface instead of retrying forever."""
    attempts: list[int] = []

    def _never_acquire():
        attempts.append(len(attempts))
        return None

    monkeypatch.setattr(
        client_module.HostRuntimeProvider,
        "acquire_capability",
        _never_acquire,
    )
    monkeypatch.setattr(client_module, "_ACQUIRE_RETRY_DELAY_SECONDS", 0.0)

    acquired = await ComputerUseClient._acquire_capability()

    assert acquired is None
    assert len(attempts) == client_module._ACQUIRE_ATTEMPTS


def test_observe_windows_seeds_then_reports_new_windows() -> None:
    """First observation seeds the baseline; later ones surface new windows."""
    client = ComputerUseClient("session-x", lambda: _FakeTransport())

    assert client.observe_windows([{"id": "1", "title": "Editor"}]) == []

    new = client.observe_windows(
        [{"id": "1", "title": "Editor"}, {"id": "9", "title": "Save As"}]
    )
    assert [window["id"] for window in new] == ["9"]

    # A closed window updates the baseline without reporting anything new.
    assert client.observe_windows([{"id": "1", "title": "Editor"}]) == []


def test_dialog_hint_lists_new_windows() -> None:
    hint = _dialog_hint([{"id": "9", "title": "Save As"}])

    assert "id=9" in hint
    assert "Save As" in hint
    assert "observe_window" in hint


@pytest.mark.asyncio
async def test_note_new_windows_attaches_hint_for_opened_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A control action that opens a window must annotate its result."""
    client = ComputerUseClient("session-y", lambda: _FakeTransport())
    client.observe_windows([{"id": "1", "title": "Editor"}])

    async def _fake_execute(method, params, *, deadline_ms=10000):
        assert method == "list_windows"
        return {
            "windows": [
                {"id": "1", "title": "Editor"},
                {"id": "9", "title": "Save As"},
            ]
        }

    monkeypatch.setattr(client, "execute", _fake_execute)

    payload: dict[str, Any] = {"ok": True, "action": "press_key"}
    await _note_new_windows(client, payload)

    assert "id=9" in payload["hint"]


@pytest.mark.asyncio
async def test_note_new_windows_stays_silent_without_new_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No new window means no hint is added to the acknowledgement."""
    client = ComputerUseClient("session-z", lambda: _FakeTransport())
    client.observe_windows([{"id": "1", "title": "Editor"}])

    async def _fake_execute(method, params, *, deadline_ms=10000):
        return {"windows": [{"id": "1", "title": "Editor"}]}

    monkeypatch.setattr(client, "execute", _fake_execute)

    payload: dict[str, Any] = {"ok": True, "action": "type"}
    await _note_new_windows(client, payload)

    assert "hint" not in payload


@pytest.mark.asyncio
async def test_note_new_windows_ignores_probe_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed probe must not raise or annotate the action result."""
    client = ComputerUseClient("session-w", lambda: _FakeTransport())
    client.observe_windows([{"id": "1", "title": "Editor"}])

    async def _boom(method, params, *, deadline_ms=10000):
        raise RuntimeError("transport down")

    monkeypatch.setattr(client, "execute", _boom)

    payload: dict[str, Any] = {"ok": True, "action": "click"}
    await _note_new_windows(client, payload)

    assert "hint" not in payload
