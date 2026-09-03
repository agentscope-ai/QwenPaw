# -*- coding: utf-8 -*-
"""Tests for the Relay Node reconnect supervisor."""
from __future__ import annotations

import asyncio

import pytest

from qwenpaw.remote_access import RelayNodeSupervisor


@pytest.mark.asyncio
async def test_supervisor_has_one_bounded_reconnect_loop() -> None:
    attempts = 0
    delays: list[float] = []
    reached = asyncio.Event()

    class FailingConnection:
        async def connect_once(self) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 3:
                reached.set()
            raise ConnectionError("offline")

    async def no_wait(delay: float) -> None:
        delays.append(delay)
        await asyncio.sleep(0)

    supervisor = RelayNodeSupervisor(  # type: ignore[arg-type]
        FailingConnection(),
        sleep=no_wait,
        jitter=lambda delay: delay,
    )
    supervisor.start()
    supervisor.start()
    await asyncio.wait_for(reached.wait(), timeout=1)
    await supervisor.stop()

    assert attempts >= 3
    assert delays[:2] == [1.0, 2.0]
    assert supervisor.last_error == "ConnectionError"
