# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Waiting for another session's turn at the desktop.

The helper refuses immediately when another session holds the desktop rather
than queueing the request, so the waiting happens on this side. That placement
is the point: a thread parked inside the helper is not reading its connection,
so a stop could not reach it, and it would wake later to act on a desktop the
user had already withdrawn.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from computer_use import client as client_module
from computer_use.client import ComputerUseClient
from computer_use.protocol import ComputerUseProtocolError


class _Transport:
    """A transport that reports the desktop busy a fixed number of times."""

    def __init__(self, busy_replies: int) -> None:
        self.busy_replies = busy_replies
        self.attempts = 0
        self.closed = False

    def set_reverse_request_handler(self, _handler: Any) -> None:
        return None

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True

    async def request(self, message: dict[str, Any]) -> dict[str, Any]:
        self.attempts += 1
        if self.attempts <= self.busy_replies:
            raise ComputerUseProtocolError(
                "desktop_busy",
                "Another Computer Use session is using the desktop.",
            )
        return {
            "protocol_version": message["protocol_version"],
            "request_id": message["request_id"],
            "ok": True,
            "result": {"done": True},
        }


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch: pytest.MonkeyPatch):
    """Keep the backoff from making the suite wait for real seconds."""
    monkeypatch.setattr(client_module, "_DESKTOP_BUSY_DELAY_SECONDS", 0.001)
    yield


@pytest.mark.asyncio
async def test_a_busy_desktop_is_retried_until_it_frees_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        client_module,
        "get_current_computer_use_turn_id",
        lambda: "turn-1",
    )
    transport = _Transport(busy_replies=2)
    client = ComputerUseClient(
        "session-1",
        transport_factory=lambda: transport,
    )
    client._observation_id = "observation-1"

    result = await client.execute("click", {})

    assert result == {"done": True}
    assert transport.attempts == 3, "should have retried past both refusals"


@pytest.mark.asyncio
async def test_a_desktop_busy_for_too_long_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model is told, rather than left waiting indefinitely."""
    monkeypatch.setattr(
        client_module,
        "get_current_computer_use_turn_id",
        lambda: "turn-1",
    )
    transport = _Transport(busy_replies=99)
    client = ComputerUseClient(
        "session-1",
        transport_factory=lambda: transport,
    )
    client._observation_id = "observation-1"

    with pytest.raises(ComputerUseProtocolError) as refusal:
        await client.execute("click", {})

    assert refusal.value.code == "desktop_busy"
    assert transport.attempts == client_module._DESKTOP_BUSY_ATTEMPTS


@pytest.mark.asyncio
async def test_a_stop_ends_the_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reason the waiting belongs on this side.

    A stop arriving while the desktop is busy must end the attempts. Inside the
    helper the same wait could not be interrupted, and the queued input would
    land after the user had already stopped it.
    """
    monkeypatch.setattr(
        client_module,
        "get_current_computer_use_turn_id",
        lambda: "turn-1",
    )
    transport = _Transport(busy_replies=99)
    client = ComputerUseClient(
        "session-1",
        transport_factory=lambda: transport,
    )
    client._observation_id = "observation-1"

    async def _stop_once_contended() -> None:
        while transport.attempts < 1:
            await asyncio.sleep(0)
        client._stopped_turn = "turn-1"

    stopper = asyncio.create_task(_stop_once_contended())
    with pytest.raises(ComputerUseProtocolError) as refusal:
        await client.execute("click", {})
    await stopper

    assert refusal.value.code == "turn_stopped"
    assert (
        transport.attempts < client_module._DESKTOP_BUSY_ATTEMPTS
    ), "the retrying should have stopped early rather than using every attempt"


@pytest.mark.asyncio
async def test_other_failures_are_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only this refusal is safe to repeat.

    It is raised before the helper touches anything. A timeout is not: the
    action may already have happened, and repeating it would click twice.
    """
    monkeypatch.setattr(
        client_module,
        "get_current_computer_use_turn_id",
        lambda: "turn-1",
    )

    class _Timeout(_Transport):
        async def request(self, message: dict[str, Any]) -> dict[str, Any]:
            self.attempts += 1
            raise ComputerUseProtocolError("request_timeout", "too slow")

    transport = _Timeout(busy_replies=0)
    client = ComputerUseClient(
        "session-1",
        transport_factory=lambda: transport,
    )
    client._observation_id = "observation-1"

    with pytest.raises(ComputerUseProtocolError) as failure:
        await client.execute("click", {})

    assert failure.value.code == "request_timeout"
    assert transport.attempts == 1, "a timeout must be reported, not repeated"


@pytest.mark.asyncio
async def test_user_intervention_is_a_retryable_soft_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The recency guard's refusal must not tear down the connection.

    Removing the post-approval exemption means an action right after an
    approval can be refused as ``user_intervention``. The design relies on that
    being recoverable: the caller observes again and reissues once the grace
    has passed. So it has to surface as a plain action-level error on a live
    connection -- not discard the transport the way a broken pipe would, or the
    retry would pay for a fresh connect every time.
    """
    monkeypatch.setattr(
        client_module,
        "get_current_computer_use_turn_id",
        lambda: "turn-1",
    )

    class _Intervene(_Transport):
        def __init__(self) -> None:
            super().__init__(busy_replies=0)
            self.methods: list[str] = []

        async def request(self, message: dict[str, Any]) -> dict[str, Any]:
            self.attempts += 1
            self.methods.append(message["method"])
            if self.attempts == 1:
                raise ComputerUseProtocolError(
                    "user_intervention",
                    "Recent user input was detected; observe again.",
                )
            if message["method"] == "observe_window":
                return {
                    "protocol_version": message["protocol_version"],
                    "request_id": message["request_id"],
                    "ok": True,
                    "result": {"observation_id": "observation-2"},
                }
            assert message["params"]["observation_id"] == "observation-2"
            return {
                "protocol_version": message["protocol_version"],
                "request_id": message["request_id"],
                "ok": True,
                "result": {"done": True},
            }

    transport = _Intervene()
    client = ComputerUseClient(
        "session-1",
        transport_factory=lambda: transport,
    )
    client._observation_id = "observation-1"

    with pytest.raises(ComputerUseProtocolError) as refusal:
        await client.execute("click", {})
    assert refusal.value.code == "user_intervention"
    # The connection is intact: not closed, and not retried behind the caller's
    # back -- a soft refusal, not a transport failure.
    assert transport.closed is False
    assert transport.attempts == 1

    # The caller observes again and reissues with the fresh observation on the
    # same connection; it works.
    observed = await client.execute(
        "observe_window",
        {"window_id": "window-1"},
    )
    result = await client.execute("click", {})
    assert observed == {}
    assert result == {"done": True}
    assert transport.methods == ["click", "observe_window", "click"]
    assert transport.attempts == 3
