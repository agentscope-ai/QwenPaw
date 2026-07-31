# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Stopping Computer Use: promptness, and which event loop it runs on.

Stopping used to queue behind the action it was meant to interrupt, and that
action could itself be waiting on a person answering an approval prompt. These
tests hold the two properties that fix depended on: a stop lands while an
action is in flight, and it survives the connection being replaced afterwards.
A third covers the control route arriving on a different event loop from the
one that owns the transport, which is how the host actually calls it.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Mapping
from typing import Any

import pytest

from computer_use_tool.client import ComputerUseClient
from computer_use_tool.protocol import ComputerUseProtocolError
from computer_use_tool.transport import (
    ComputerUseTransport,
    ReverseRequestHandler,
)
from qwenpaw.app.computer_use import set_current_computer_use_turn_id


class _StallingTransport(ComputerUseTransport):
    """A transport whose reply never arrives until the connection is closed.

    Stands in for the helper blocked mid-action -- including blocked on a
    person answering an approval prompt, which is the unbounded case.
    """

    def __init__(self) -> None:
        self.closed = False
        self.in_flight = asyncio.Event()
        self._pending: list[asyncio.Future[dict[str, Any]]] = []

    async def connect(self) -> None:
        return None

    async def request(self, message: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(message)
        if payload["method"] == "hello":
            return {
                "request_id": payload["request_id"],
                "ok": True,
                "result": {"protocol_version": 1},
            }
        future: asyncio.Future[
            dict[str, Any]
        ] = asyncio.get_running_loop().create_future()
        self._pending.append(future)
        self.in_flight.set()
        return await future

    async def close(self) -> None:
        self.closed = True
        # Closing rejects whatever was still waiting, the way both real
        # transports do; without that a stop could not end a stalled action.
        for future in self._pending:
            if not future.done():
                future.set_exception(
                    ComputerUseProtocolError(
                        "runtime_disconnected",
                        "Computer Use connection closed.",
                    ),
                )
        self._pending.clear()

    def set_reverse_request_handler(
        self,
        handler: ReverseRequestHandler,
    ) -> None:
        return None


@pytest.mark.asyncio
async def test_stop_lands_while_an_action_is_still_waiting() -> None:
    """A stop must not wait for the action it is interrupting."""
    transport = _StallingTransport()
    client = ComputerUseClient("session-stop", lambda: transport)
    set_current_computer_use_turn_id("turn-stop")
    try:
        action = asyncio.create_task(client.execute("observe_window", {}))
        await asyncio.wait_for(transport.in_flight.wait(), timeout=2)

        stopped = await asyncio.wait_for(client.stop_turn(), timeout=2)
        assert stopped is True

        with pytest.raises(ComputerUseProtocolError) as failure:
            await asyncio.wait_for(action, timeout=2)
        assert failure.value.code == "runtime_disconnected"
        assert transport.closed is True
    finally:
        set_current_computer_use_turn_id(None)


@pytest.mark.asyncio
async def test_a_stopped_turn_stays_stopped_on_a_fresh_connection() -> None:
    """Stopping drops the connection, so the refusal cannot live only there."""
    first = _StallingTransport()
    second = _StallingTransport()
    handed_out = iter((first, second))
    client = ComputerUseClient("session-stop-2", lambda: next(handed_out))
    set_current_computer_use_turn_id("turn-stop-2")
    try:
        action = asyncio.create_task(client.execute("observe_window", {}))
        await asyncio.wait_for(transport_ready(first), timeout=2)
        await client.stop_turn()
        with pytest.raises(ComputerUseProtocolError):
            await asyncio.wait_for(action, timeout=2)

        # Same turn, new transport: the helper it would connect to knows
        # nothing about the stop, so the client has to refuse this itself.
        with pytest.raises(ComputerUseProtocolError) as failure:
            await client.execute("observe_window", {})
        assert failure.value.code == "turn_stopped"
        assert second.closed is False
    finally:
        set_current_computer_use_turn_id(None)


@pytest.mark.asyncio
async def test_a_later_turn_is_not_refused_by_an_earlier_stop() -> None:
    """The refusal is scoped to the turn that was stopped, not the session."""
    transport = _StallingTransport()
    replacement = _StallingTransport()
    handed_out = iter((transport, replacement))
    client = ComputerUseClient("session-stop-3", lambda: next(handed_out))
    set_current_computer_use_turn_id("turn-a")
    try:
        action = asyncio.create_task(client.execute("observe_window", {}))
        await asyncio.wait_for(transport_ready(transport), timeout=2)
        await client.stop_turn()
        with pytest.raises(ComputerUseProtocolError):
            await asyncio.wait_for(action, timeout=2)

        set_current_computer_use_turn_id("turn-b")
        following = asyncio.create_task(client.execute("observe_window", {}))
        # It reaches the transport rather than being refused outright.
        await asyncio.wait_for(transport_ready(replacement), timeout=2)
        following.cancel()
    finally:
        set_current_computer_use_turn_id(None)


def test_stop_arriving_on_another_event_loop_is_handed_back() -> None:
    """The host calls stop from the HTTP loop, not the workspace's own.

    The transport's streams, its reader task and the client's lock all belong
    to the loop that built them, so the stop has to run there. Without that the
    await either blocks on a lock the other loop owns or touches its objects.
    """
    owner_loop = asyncio.new_event_loop()
    ready = threading.Event()

    def run_owner() -> None:
        asyncio.set_event_loop(owner_loop)
        ready.set()
        owner_loop.run_forever()

    thread = threading.Thread(target=run_owner, name="owner-loop", daemon=True)
    thread.start()
    ready.wait(timeout=5)

    transport = _StallingTransport()
    client = ComputerUseClient("session-cross", lambda: transport)

    async def start_action() -> asyncio.Task[Any]:
        set_current_computer_use_turn_id("turn-cross")
        return asyncio.create_task(client.execute("observe_window", {}))

    action = asyncio.run_coroutine_threadsafe(
        start_action(),
        owner_loop,
    ).result(5)
    assert asyncio.run_coroutine_threadsafe(
        transport_ready(transport),
        owner_loop,
    ).result(5)

    # A second loop, standing in for the HTTP server's.
    caller_loop = asyncio.new_event_loop()
    try:
        # Bounded on both sides: a stop that has to wait for the action would
        # otherwise hang the suite rather than report a failure.
        stopped = caller_loop.run_until_complete(
            asyncio.wait_for(client.stop_turn(), timeout=5),
        )
        assert stopped is True
        assert transport.closed is True
    finally:
        owner_loop.call_soon_threadsafe(action.cancel)
        # Drain whatever the cancelled action leaves behind before stopping the
        # loop, so a failure above cannot leave this thread alive.
        owner_loop.call_soon_threadsafe(owner_loop.stop)
        thread.join(timeout=5)
        caller_loop.close()
        owner_loop.close()
        set_current_computer_use_turn_id(None)


async def transport_ready(transport: _StallingTransport) -> bool:
    """Wait until the transport is holding a request open."""
    await transport.in_flight.wait()
    return True
