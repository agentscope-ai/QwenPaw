# -*- coding: utf-8 -*-
"""WebSocket relay lifecycle tests for QwenPaw Hub."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.frames import Close

from qwenpaw.hub import websocket_proxy
from qwenpaw.hub.websocket_proxy import _upstream_to_client


class _Client:
    def __init__(
        self,
        messages: list[dict[str, object]] | None = None,
    ) -> None:
        self.messages = list(messages or [])
        self.headers: dict[str, str] = {}
        self.sent: list[str | bytes] = []
        self.accepted_protocol: str | None = None
        self.closed: tuple[int, str] | None = None

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accepted_protocol = subprotocol

    async def receive(self) -> dict[str, object]:
        return self.messages.pop(0)

    async def send_text(self, message: str) -> None:
        self.sent.append(message)

    async def send_bytes(self, message: bytes) -> None:
        self.sent.append(message)

    async def close(self, code: int, reason: str = "") -> None:
        self.closed = (code, reason)


class _Upstream:
    def __init__(self, messages: list[str | bytes] | None = None) -> None:
        self.messages = list(messages or [])
        self.sent: list[str | bytes] = []
        self.closed: int | None = None
        self.close_code = 1000
        self.close_reason = "complete"
        self.subprotocol: str | None = None

    def __aiter__(self) -> _Upstream:
        return self

    async def __anext__(self) -> str | bytes:
        if self.messages:
            return self.messages.pop(0)
        raise StopAsyncIteration

    async def send(self, message: str | bytes) -> None:
        self.sent.append(message)

    async def close(self, code: int) -> None:
        self.closed = code


class _ClosedUpstream(_Upstream):
    async def __anext__(self) -> str | bytes:
        raise ConnectionClosed(
            Close(4002, "upstream closed"),
            None,
        )


class _WaitingClient(_Client):
    async def receive(self) -> dict[str, object]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _WaitingUpstream(_Upstream):
    async def __anext__(self) -> str | bytes:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _ConnectContext:
    def __init__(self, upstream: _Upstream) -> None:
        self.upstream = upstream

    async def __aenter__(self) -> _Upstream:
        return self.upstream

    async def __aexit__(self, *args: object) -> None:
        del args


@pytest.mark.asyncio
async def test_upstream_close_code_reaches_client() -> None:
    client = _Client()

    await _upstream_to_client(
        cast(Any, client),
        cast(Any, _ClosedUpstream()),
    )

    assert client.closed == (4002, "upstream closed")


@pytest.mark.asyncio
async def test_relay_cancels_upstream_pump_after_client_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client(
        [
            {"type": "websocket.receive", "text": "hello"},
            {"type": "websocket.disconnect", "code": 4001},
        ],
    )
    client.headers["sec-websocket-protocol"] = "chat"
    upstream = _WaitingUpstream()
    upstream.subprotocol = "chat"
    captured: dict[str, object] = {}

    def connect(url: str, **kwargs: object) -> _ConnectContext:
        captured["url"] = url
        captured.update(kwargs)
        return _ConnectContext(upstream)

    monkeypatch.setattr(websocket_proxy, "connect", connect)

    await websocket_proxy.relay_websocket(
        cast(Any, client),
        "ws://runtime/api/ws",
        headers={"X-QwenPaw-Runtime-Token": "secret"},
        max_size=16 * 1024 * 1024,
    )

    assert client.accepted_protocol == "chat"
    assert upstream.sent == ["hello"]
    assert upstream.closed == 4001
    assert captured["additional_headers"] == {
        "X-QwenPaw-Runtime-Token": "secret",
    }
    assert captured["max_size"] == 16 * 1024 * 1024


@pytest.mark.asyncio
async def test_relay_cancels_client_pump_after_upstream_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _WaitingClient()
    upstream = _Upstream(["reply"])

    monkeypatch.setattr(
        websocket_proxy,
        "connect",
        lambda *args, **kwargs: _ConnectContext(upstream),
    )

    await websocket_proxy.relay_websocket(
        cast(Any, client),
        "ws://runtime/api/ws",
        headers={"X-QwenPaw-Runtime-Token": "secret"},
        max_size=16 * 1024 * 1024,
    )

    assert client.sent == ["reply"]
    assert client.closed == (1000, "complete")
