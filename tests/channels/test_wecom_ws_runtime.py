# -*- coding: utf-8 -*-

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for candidate in (ROOT, SRC):
    path_str = str(candidate)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from copaw.app.channels.wecom.ws_client import WeComRuntimeClient


class _FakeWSMessage:
    def __init__(self, data: str, msg_type: int = 1):
        self.data = data
        self.type = msg_type


class _FakeWebSocket:
    def __init__(
        self,
        messages=None,
        fail_after_messages: bool = False,
        wait_after_messages: bool = False,
    ):
        self._messages = list(messages or [])
        self.fail_after_messages = fail_after_messages
        self.wait_after_messages = wait_after_messages
        self.sent_json = []
        self.closed = False

    async def send_json(self, payload):
        self.sent_json.append(payload)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._messages:
            return self._messages.pop(0)
        if self.fail_after_messages:
            raise RuntimeError("socket dropped")
        if self.wait_after_messages:
            while not self.closed:
                await asyncio.sleep(0.01)
            raise StopAsyncIteration
        raise StopAsyncIteration

    async def close(self):
        self.closed = True


class _FakeSession:
    def __init__(self, sockets):
        self._sockets = list(sockets)
        self.ws_connect_calls = []
        self.closed = False

    async def ws_connect(self, url):
        self.ws_connect_calls.append(url)
        if not self._sockets:
            raise RuntimeError("no more sockets")
        socket = self._sockets.pop(0)
        if isinstance(socket, Exception):
            raise socket
        return socket

    async def close(self):
        self.closed = True


@pytest.mark.anyio
async def test_runtime_client_subscribes_dispatches_callbacks_and_pings():
    callback_payloads = []
    socket = _FakeWebSocket(
        messages=[
            _FakeWSMessage(
                json.dumps({"cmd": "noop"}),
            ),
            _FakeWSMessage(
                json.dumps(
                    {
                        "cmd": "aibot_msg_callback",
                        "headers": {"req_id": "req-1"},
                        "body": {"msgid": "msg-1"},
                    }
                )
            ),
            _FakeWSMessage(
                json.dumps(
                    {
                        "cmd": "aibot_event_callback",
                        "headers": {"req_id": "req-2"},
                        "body": {"event": "follow"},
                    }
                )
            ),
        ],
        wait_after_messages=True,
    )
    session = _FakeSession([socket])

    client = WeComRuntimeClient(
        bot_id="bot-1",
        secret="secret-1",
        ws_url="wss://example.test/ws",
        ping_interval_seconds=0.01,
        reconnect_min_seconds=1,
        reconnect_max_seconds=2,
        on_payload=callback_payloads.append,
        session_factory=lambda: session,
        request_id_factory=lambda: "req-fixed",
    )

    await client.start()
    await asyncio.sleep(0.05)
    await client.stop()

    assert session.ws_connect_calls == ["wss://example.test/ws"]
    assert socket.sent_json[0]["cmd"] == "aibot_subscribe"
    assert socket.sent_json[0]["body"]["bot_id"] == "bot-1"
    assert any(item["cmd"] == "ping" for item in socket.sent_json[1:])
    assert [payload["cmd"] for payload in callback_payloads] == [
        "aibot_msg_callback",
        "aibot_event_callback",
    ]
    assert socket.closed is True
    assert session.closed is True


@pytest.mark.anyio
async def test_runtime_client_reconnects_with_backoff_after_disconnect():
    sleep_calls = []
    first_socket = _FakeWebSocket(fail_after_messages=True)
    second_socket = _FakeWebSocket(wait_after_messages=True)
    session = _FakeSession([first_socket, second_socket])

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        await asyncio.sleep(0)

    client = WeComRuntimeClient(
        bot_id="bot-1",
        secret="secret-1",
        ws_url="wss://example.test/ws",
        ping_interval_seconds=60,
        reconnect_min_seconds=2,
        reconnect_max_seconds=8,
        on_payload=lambda _payload: None,
        session_factory=lambda: session,
        sleep_func=fake_sleep,
        request_id_factory=lambda: "req-fixed",
    )

    await client.start()
    await asyncio.sleep(0.05)
    await client.stop()

    assert session.ws_connect_calls == [
        "wss://example.test/ws",
        "wss://example.test/ws",
    ]
    assert sleep_calls[0] == 2
    assert first_socket.closed is True
    assert second_socket.closed is True
