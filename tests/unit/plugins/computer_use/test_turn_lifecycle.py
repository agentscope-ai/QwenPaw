# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Retiring a turn, and the cache bound that depends on it.

The host mints a turn id per request and nothing retired it, so a session that
used the tool once kept its turn, its connection and the helper's per-turn
state
indefinitely. That also made the cache bound unreachable, because a client
holding a turn is never evicted. These tests hold both halves.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from computer_use import client as client_module
from computer_use.client import (
    ComputerUseClient,
    end_computer_use_turn,
    get_computer_use_client,
)
from computer_use.protocol import ComputerUseProtocolError
from computer_use.transport import (
    ComputerUseTransport,
    ReverseRequestHandler,
)
from qwenpaw.app import agent_context
from qwenpaw.app.computer_use import set_current_computer_use_turn_id


class _RecordingTransport(ComputerUseTransport):
    def __init__(self) -> None:
        self.methods: list[str] = []
        self.closed = False

    async def connect(self) -> None:
        return None

    async def request(self, message: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(message)
        self.methods.append(str(payload["method"]))
        return {"request_id": payload["request_id"], "ok": True, "result": {}}

    async def close(self) -> None:
        self.closed = True

    def set_reverse_request_handler(
        self,
        _handler: ReverseRequestHandler,
    ) -> None:
        return None


@pytest.mark.asyncio
async def test_ending_a_turn_tells_the_helper_and_frees_the_client() -> None:
    transport = _RecordingTransport()
    client = ComputerUseClient("session-turn", lambda: transport)
    set_current_computer_use_turn_id("turn-1")
    try:
        await client.execute("observe_window", {})
        assert client.has_active_turn is True

        assert await client.end_turn() is True
        # The helper is told, so it can drop that turn's screenshots and
        # accessibility handles rather than hold them for a turn nobody will
        # mention again.
        assert "end_turn" in transport.methods
        # And the client no longer claims a turn, which is what lets the cache
        # ever evict it.
        assert client.has_active_turn is False
        # The connection stays: the next turn will want it.
        assert transport.closed is False
    finally:
        set_current_computer_use_turn_id(None)


@pytest.mark.asyncio
async def test_ending_a_turn_is_harmless_when_there_is_none() -> None:
    # The hook runs on every request, including those that never touched the
    # tool, so a session with no client or no turn must be a quiet no-op.
    assert await end_computer_use_turn("session-never-used") is False

    transport = _RecordingTransport()
    client = ComputerUseClient("session-idle", lambda: transport)
    assert await client.end_turn() is False


@pytest.mark.asyncio
async def test_the_cache_refuses_rather_than_growing_past_its_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bound that a busy session can walk past is not a bound.

    Eviction only drops clients with no turn in flight, so before turns were
    retired every cached client counted as busy and the cache grew without
    limit, each entry holding a connection.
    """
    monkeypatch.setattr(client_module, "_clients", {})
    monkeypatch.setattr(client_module, "_MAX_CACHED_CLIENTS", 3)

    busy = []
    for index in range(3):
        session = f"busy-{index}"
        transport = _RecordingTransport()
        held = ComputerUseClient(session, lambda t=transport: t)
        set_current_computer_use_turn_id(f"turn-{index}")
        await held.execute("observe_window", {})
        client_module._clients[session] = held
        busy.append(held)
    assert all(held.has_active_turn for held in busy)

    monkeypatch.setattr(
        agent_context,
        "get_current_session_id",
        lambda: "newcomer",
    )
    monkeypatch.setattr(client_module, "get_tool_session_id", lambda: "")
    try:
        with pytest.raises(ComputerUseProtocolError) as refusal:
            get_computer_use_client()
        assert refusal.value.code == "too_many_sessions"
        assert len(client_module._clients) == 3

        # Retiring one turn makes room, the way finishing a request does.
        await busy[0].end_turn()
        admitted = get_computer_use_client()
        assert admitted is client_module._clients["newcomer"]
    finally:
        set_current_computer_use_turn_id(None)


@pytest.mark.asyncio
async def test_an_evicted_client_has_its_connection_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dropping the reference alone would leave the pipe or socket open."""
    monkeypatch.setattr(client_module, "_clients", {})
    monkeypatch.setattr(client_module, "_MAX_CACHED_CLIENTS", 1)

    transport = _RecordingTransport()
    idle = ComputerUseClient("idle-session", lambda: transport)
    set_current_computer_use_turn_id("turn-idle")
    try:
        await idle.execute("observe_window", {})
        await idle.end_turn()
        client_module._clients["idle-session"] = idle

        monkeypatch.setattr(
            agent_context,
            "get_current_session_id",
            lambda: "next",
        )
        monkeypatch.setattr(client_module, "get_tool_session_id", lambda: "")
        get_computer_use_client()

        assert "idle-session" not in client_module._clients
        # Closing is handed to the loop that owns the transport rather than
        # awaited under the cache lock, so it lands a little later.
        for _ in range(100):
            if transport.closed:
                break
            await asyncio.sleep(0.01)
        assert transport.closed is True
    finally:
        set_current_computer_use_turn_id(None)
