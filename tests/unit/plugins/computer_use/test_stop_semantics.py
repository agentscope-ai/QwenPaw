# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Per-turn Computer Use stopping without terminating the shared helper."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Mapping
from typing import Any

import pytest

from computer_use.client import ComputerUseClient
from computer_use.protocol import ComputerUseProtocolError
from computer_use.transport import (
    ComputerUseTransport,
    ReverseRequestHandler,
)
from qwenpaw.app.computer_use import set_current_computer_use_turn_id


class _ControlledTransport(ComputerUseTransport):
    """Hold ordinary requests until the test chooses their native outcome."""

    def __init__(self) -> None:
        self.closed = False
        self.requests: list[dict[str, Any]] = []
        self._pending: list[
            tuple[dict[str, Any], asyncio.Future[dict[str, Any]]]
        ] = []

    async def connect(self) -> None:
        return None

    async def request(self, message: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(message)
        self.requests.append(payload)
        if payload["method"] == "end_turn":
            return self._response(payload, {})
        future: asyncio.Future[
            dict[str, Any]
        ] = asyncio.get_running_loop().create_future()
        self._pending.append((payload, future))
        return await future

    async def close(self) -> None:
        self.closed = True
        for _, future in self._pending:
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

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def complete_next(self, result: dict[str, Any] | None = None) -> None:
        payload, future = self._pending.pop(0)
        future.set_result(self._response(payload, result or {}))

    @staticmethod
    def _response(
        request: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "protocol_version": request["protocol_version"],
            "request_id": request["request_id"],
            "ok": True,
            "result": dict(result),
        }


@pytest.mark.asyncio
async def test_stop_marks_before_waiting_for_the_current_action() -> None:
    transport = _ControlledTransport()
    client = ComputerUseClient("session-stop", lambda: transport)
    set_current_computer_use_turn_id("turn-stop")
    try:
        action = asyncio.create_task(client.execute("observe_window", {}))
        await wait_for_pending(transport)

        stopping = asyncio.create_task(client.stop_turn())
        await asyncio.sleep(0)
        assert client._stopped_turn == "turn-stop"
        assert (
            not stopping.done()
        ), "stop should let the dispatched action settle"

        transport.complete_next()
        with pytest.raises(ComputerUseProtocolError) as failure:
            await action
        assert failure.value.code == "turn_stopped"
        assert await stopping is True
        assert transport.closed is False
        assert [request["method"] for request in transport.requests] == [
            "observe_window",
            "end_turn",
        ]
    finally:
        set_current_computer_use_turn_id(None)


@pytest.mark.asyncio
async def test_a_request_queued_before_stop_cannot_cross_the_lock() -> None:
    transport = _ControlledTransport()
    client = ComputerUseClient("session-queued", lambda: transport)
    set_current_computer_use_turn_id("turn-queued")
    try:
        current = asyncio.create_task(client.execute("observe_window", {}))
        await wait_for_pending(transport)
        queued = asyncio.create_task(client.execute("list_windows", {}))
        stopping = asyncio.create_task(client.stop_turn())
        await asyncio.sleep(0)

        transport.complete_next()
        for task in (current, queued):
            with pytest.raises(ComputerUseProtocolError) as failure:
                await task
            assert failure.value.code == "turn_stopped"
        assert await stopping is True
        assert [request["method"] for request in transport.requests] == [
            "observe_window",
            "end_turn",
        ]
    finally:
        set_current_computer_use_turn_id(None)


@pytest.mark.asyncio
async def test_stopping_one_client_does_not_close_another_connection() -> None:
    first_transport = _ControlledTransport()
    second_transport = _ControlledTransport()
    first = ComputerUseClient("session-a", lambda: first_transport)
    second = ComputerUseClient("session-b", lambda: second_transport)
    set_current_computer_use_turn_id("turn-shared")
    try:
        first_action = asyncio.create_task(first.execute("observe_window", {}))
        second_action = asyncio.create_task(
            second.execute("observe_window", {}),
        )
        await wait_for_pending(first_transport)
        await wait_for_pending(second_transport)

        stopping = asyncio.create_task(first.stop_turn())
        first_transport.complete_next()
        with pytest.raises(ComputerUseProtocolError):
            await first_action
        assert await stopping is True

        second_transport.complete_next({"observation_id": "observation-b"})
        assert await second_action == {}
        assert first_transport.closed is False
        assert second_transport.closed is False
    finally:
        set_current_computer_use_turn_id(None)


@pytest.mark.asyncio
async def test_a_later_turn_is_not_refused_by_an_earlier_stop() -> None:
    transport = _ControlledTransport()
    client = ComputerUseClient("session-later", lambda: transport)
    set_current_computer_use_turn_id("turn-a")
    try:
        action = asyncio.create_task(client.execute("observe_window", {}))
        await wait_for_pending(transport)
        stopping = asyncio.create_task(client.stop_turn())
        transport.complete_next()
        with pytest.raises(ComputerUseProtocolError):
            await action
        assert await stopping is True

        set_current_computer_use_turn_id("turn-b")
        following = asyncio.create_task(client.execute("observe_window", {}))
        await wait_for_pending(transport)
        transport.complete_next({"observation_id": "observation-b"})
        assert await following == {}
    finally:
        set_current_computer_use_turn_id(None)


def test_stop_arriving_on_another_event_loop_is_handed_back() -> None:
    owner_loop = asyncio.new_event_loop()
    ready = threading.Event()

    def run_owner() -> None:
        asyncio.set_event_loop(owner_loop)
        ready.set()
        owner_loop.run_forever()

    thread = threading.Thread(target=run_owner, name="owner-loop", daemon=True)
    thread.start()
    ready.wait(timeout=5)

    transport = _ControlledTransport()
    client = ComputerUseClient("session-cross", lambda: transport)

    async def start_action() -> asyncio.Task[Any]:
        set_current_computer_use_turn_id("turn-cross")
        return asyncio.create_task(client.execute("observe_window", {}))

    action = asyncio.run_coroutine_threadsafe(
        start_action(),
        owner_loop,
    ).result(5)
    asyncio.run_coroutine_threadsafe(
        wait_for_pending(transport),
        owner_loop,
    ).result(5)

    caller_loop = asyncio.new_event_loop()
    released = threading.Event()

    def release_after_stop_mark() -> None:
        for _ in range(5_000):
            if client._stopped_turn == "turn-cross":
                owner_loop.call_soon_threadsafe(transport.complete_next)
                released.set()
                return
            threading.Event().wait(0.001)

    releaser = threading.Thread(target=release_after_stop_mark, daemon=True)
    releaser.start()
    try:
        stopped = caller_loop.run_until_complete(
            asyncio.wait_for(client.stop_turn(), timeout=5),
        )
        assert stopped is True
        assert released.wait(timeout=5)
        with pytest.raises(ComputerUseProtocolError):
            action.result()
        assert transport.closed is False
    finally:
        releaser.join(timeout=5)
        owner_loop.call_soon_threadsafe(owner_loop.stop)
        thread.join(timeout=5)
        caller_loop.close()
        owner_loop.close()
        set_current_computer_use_turn_id(None)


async def wait_for_pending(transport: _ControlledTransport) -> None:
    for _ in range(1_000):
        if transport.pending_count:
            return
        await asyncio.sleep(0)
    raise AssertionError("transport did not receive a request")
