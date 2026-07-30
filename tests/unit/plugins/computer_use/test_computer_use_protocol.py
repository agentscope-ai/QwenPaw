# -*- coding: utf-8 -*-
"""Tests for the thin Computer Use protocol adapter."""

# Tests reach into module internals to pin the protocol contract, and their
# fakes deliberately accept arguments they ignore to match real signatures.
# pylint: disable=protected-access, unused-argument, unnecessary-lambda
# pylint: disable=useless-return, use-implicit-booleaness-not-comparison

from __future__ import annotations

from collections.abc import Iterator, Mapping
import json
import socket
import threading
from typing import Any

import pytest

from agentscope.message import ToolResultState
import computer_use_tool.client as client_module
from computer_use_tool.client import ComputerUseClient
from computer_use_tool.dispatch import (
    _element_line,
    _error,
    _native_request,
    _response,
    _with_compact_elements,
)
from computer_use_tool.protocol import ComputerUseProtocolError
from computer_use_tool.transport.base import (
    ComputerUseTransport,
    ReverseRequestHandler,
)
from qwenpaw.app.computer_use import (
    HostRuntimeProvider,
    set_current_computer_use_turn_id,
)
from qwenpaw.app.computer_use import runtime as runtime_module


@pytest.fixture(autouse=True)
def _reset_host_runtime(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in (
        "QWENPAW_COMPUTER_USE_PIPE",
        "QWENPAW_COMPUTER_USE_CAPABILITY",
        "QWENPAW_COMPUTER_USE_PROTOCOL",
        "QWENPAW_COMPUTER_USE_CONTROL_HOST",
        "QWENPAW_COMPUTER_USE_CONTROL_PORT",
        "QWENPAW_COMPUTER_USE_CONTROL_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    HostRuntimeProvider._capability = None
    yield
    HostRuntimeProvider._capability = None


def test_host_runtime_requests_a_capability_only_when_needed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_module.sys, "platform", "darwin")
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
                    b'{"ok":true,"pipe_name":"pipe-1",'
                    b'"capability":"secret-1"}\n',
                )
                stream.flush()

    server = threading.Thread(target=_serve_once)
    server.start()
    monkeypatch.setenv("QWENPAW_COMPUTER_USE_CONTROL_HOST", "127.0.0.1")
    monkeypatch.setenv("QWENPAW_COMPUTER_USE_CONTROL_PORT", str(port))
    monkeypatch.setenv("QWENPAW_COMPUTER_USE_CONTROL_TOKEN", token)

    assert HostRuntimeProvider.is_available() is True
    assert received == {}
    capability = HostRuntimeProvider.acquire_capability()
    server.join(timeout=1)

    assert capability == runtime_module.RuntimeCapability(
        "pipe-1",
        "secret-1",
        1,
    )
    assert received == {
        "token": token,
        "action": "acquire",
    }


def test_coordinate_input_uses_one_observation_context() -> None:
    method, params, include_images = _native_request(
        "click",
        observation_id="observation-1",
        x=40,
        y=60,
        button="left",
        count=1,
    )

    assert method == "click"
    assert include_images is False
    assert params == {
        "observation_id": "observation-1",
        "x": 40,
        "y": 60,
        "button": "left",
        "count": 1,
    }


def test_close_window_maps_to_the_native_method() -> None:
    """Closing acts through the observation and returns no screenshot."""
    method, params, include_images = _native_request(
        "close_window",
        observation_id="observation-1",
    )

    assert method == "close_window"
    assert params == {"observation_id": "observation-1"}
    assert include_images is False


def test_close_window_requires_an_observation() -> None:
    with pytest.raises(ValueError, match="observation_id"):
        _native_request("close_window", observation_id="")


def test_coordinate_input_rejects_missing_observation() -> None:
    with pytest.raises(ValueError, match="observation_id"):
        _native_request(
            "click",
            observation_id="",
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
    text_blocks = [block for block in response.content if block.type == "text"]
    assert len(image_blocks) == 1
    assert str(image_blocks[0].source.url) == data_url
    assert len(text_blocks) == 1
    assert data_url not in text_blocks[0].text
    assert "screenshot-1" in text_blocks[0].text


def test_native_error_marks_the_tool_call_as_failed() -> None:
    response = _error("stale_observation", "Observe the window again.")

    assert response.state == ToolResultState.ERROR
    assert '"ok":false' in response.content[-1].text


def test_uia_input_uses_observation_and_element() -> None:
    method, params, _ = _native_request(
        "invoke",
        observation_id="observation-1",
        element_id="uia-7",
    )

    assert method == "invoke_element"
    assert params == {
        "observation_id": "observation-1",
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

    def set_reverse_request_handler(
        self,
        handler: ReverseRequestHandler,
    ) -> None:
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
async def test_acquire_capability_rejects_an_incompatible_desktop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        client_module.HostRuntimeProvider,
        "acquire_capability",
        lambda: runtime_module.RuntimeCapability("pipe-1", "secret-1", 2),
    )

    with pytest.raises(ComputerUseProtocolError) as refusal:
        await ComputerUseClient._acquire_capability()

    assert refusal.value.code == "protocol_mismatch"


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


@pytest.mark.asyncio
async def test_no_action_ever_carries_a_post_approval_exemption() -> None:
    """The client never sends after_approval, on any path.

    The exemption is gone: the recency guard has no bypass, so an action right
    after an approval is refused as retryable user_intervention rather than
    waved through by a client-held flag. The client therefore has no mechanism
    left to attach the flag, and this pins that it is absent.
    """
    transport = _FakeTransport()
    client = ComputerUseClient("session-a", lambda: transport)
    set_current_computer_use_turn_id("turn-1")
    try:
        await client.execute(
            "type_text",
            {"observation_id": "observation-1", "text": "x"},
        )
        assert "after_approval" not in transport.messages[-1]["params"]

        await client.execute("click", {"observation_id": "observation-1"})
        assert "after_approval" not in transport.messages[-1]["params"]
    finally:
        set_current_computer_use_turn_id(None)


def test_the_approval_coordinator_holds_no_exemption_state() -> None:
    """Nothing to arm, so nothing to leak across turns or apps."""
    assert not hasattr(
        client_module.ComputerUseApprovalCoordinator(),
        "intervention_bypass_pending",
    )


def test_element_line_uses_bounds_centre_on_windows() -> None:
    """Windows elements expose pixel bounds, rendered as a centre point."""
    line = _element_line(
        {
            "id": "uia-1",
            "control_type_name": "Edit",
            "name": "text editor",
            "bounds": [100, 200, 300, 400],
            "enabled": True,
            "offscreen": False,
        },
    )
    assert line == 'uia-1 Edit "text editor" screen@200,300'


def test_element_line_uses_value_on_macos() -> None:
    """macOS elements carry a value instead of bounds."""
    line = _element_line(
        {
            "id": "ax-2",
            "role": "AXTextArea",
            "control_type_name": "Edit",
            "name": "note",
            "value": "hello",
        },
    )
    assert line == 'ax-2 Edit "note" =hello'


def test_element_line_keeps_disabled_and_offscreen_visible() -> None:
    """Both states stay in the listing: they inform the next decision."""
    line = _element_line(
        {
            "id": "uia-9",
            "control_type_name": "Button",
            "name": "Save",
            "bounds": [0, 0, 10, 10],
            "enabled": False,
            "offscreen": True,
        },
    )
    assert line == 'uia-9 Button "Save" screen@5,5 [disabled] [offscreen]'


def test_compact_elements_preserves_protocol_fields() -> None:
    """Only the element listing changes; binding fields stay untouched."""
    payload = {
        "ok": True,
        "action": "observe_window",
        "observation_id": "observation-1",
        "window": {"id": "42", "title": "Editor"},
        "accessibility": {
            "available": True,
            "elements": [
                {
                    "id": "uia-0",
                    "control_type_name": "Window",
                    "name": "Editor",
                    "bounds": [0, 0, 100, 100],
                },
                {
                    "id": "uia-1",
                    "control_type_name": "Button",
                    "name": "OK",
                    "bounds": [10, 10, 30, 30],
                },
            ],
        },
    }
    result = _with_compact_elements(payload)

    assert result["observation_id"] == "observation-1"
    assert result["window"] == {"id": "42", "title": "Editor"}
    assert result["accessibility"]["available"] is True
    assert result["accessibility"]["elements"] == (
        'uia-0 Window "Editor" screen@50,50\n' 'uia-1 Button "OK" screen@20,20'
    )
    # The original payload must not be mutated.
    accessibility = payload["accessibility"]
    assert isinstance(accessibility, Mapping)
    assert isinstance(accessibility["elements"], list)


def test_compact_elements_ignores_payloads_without_accessibility() -> None:
    """Input actions return no accessibility block and pass through."""
    payload = {"ok": True, "action": "click", "applied": True}
    assert _with_compact_elements(payload) == payload


def test_response_text_is_compact_and_carries_summary_fields() -> None:
    """The model-facing text drops indentation and keeps summary fields."""
    payload = {
        "ok": True,
        "action": "observe_window",
        "accessibility": {
            "available": True,
            "focused_element": 'uia-1 Edit "text editor" screen@200,300',
            "document_text": "hello world",
            "elements": [
                {
                    "id": "uia-1",
                    "control_type_name": "Edit",
                    "name": "text editor",
                    "bounds": [100, 200, 300, 400],
                },
            ],
        },
    }
    text = _response(payload).content[-1].text

    assert "\n  " not in text
    decoded = json.loads(text)
    accessibility = decoded["accessibility"]
    assert accessibility["focused_element"] == (
        'uia-1 Edit "text editor" screen@200,300'
    )
    assert accessibility["document_text"] == "hello world"
    assert accessibility["elements"] == (
        'uia-1 Edit "text editor" screen@200,300'
    )
