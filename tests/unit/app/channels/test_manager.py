# -*- coding: utf-8 -*-
"""Tests for channel startup lifecycle management."""

# pylint: disable=protected-access

import asyncio
from unittest.mock import AsyncMock, call

import pytest

from qwenpaw.app.channels import manager as manager_module
from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.exceptions import ChannelError, ChannelStartupError


class _FakeChannel:
    """Minimal channel double with deterministic startup outcomes."""

    channel = "test"
    uses_manager_queue = True

    def __init__(self, outcomes: list[Exception | None]) -> None:
        self._outcomes = list(outcomes)
        self.start_attempts = 0
        self.stop_attempts = 0
        self.first_attempt = asyncio.Event()
        self.started = asyncio.Event()
        self.enqueue_callback = None

    def set_enqueue(self, callback) -> None:
        self.enqueue_callback = callback

    async def start(self) -> None:
        self.start_attempts += 1
        self.first_attempt.set()
        outcome = self._outcomes.pop(0) if self._outcomes else None
        if outcome is not None:
            raise outcome
        self.started.set()

    async def stop(self) -> None:
        self.stop_attempts += 1


def _retryable_error() -> ChannelStartupError:
    return ChannelStartupError(
        channel_name="test",
        message="dependency is temporarily unavailable",
    )


@pytest.mark.asyncio
async def test_start_all_retries_retryable_failure_until_recovered(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        manager_module,
        "_CHANNEL_START_RETRY_INITIAL_DELAY",
        0.0,
    )
    channel = _FakeChannel([_retryable_error(), None])
    manager = ChannelManager([channel])

    await manager.start_all()
    await asyncio.wait_for(channel.started.wait(), timeout=1.0)

    assert channel.start_attempts == 2
    assert channel.stop_attempts == 1
    await manager.stop_all()


@pytest.mark.asyncio
async def test_startup_retry_backoff_is_capped(monkeypatch) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr(manager_module.asyncio, "sleep", sleep)
    monkeypatch.setattr(
        manager_module,
        "_CHANNEL_START_RETRY_INITIAL_DELAY",
        2.0,
    )
    monkeypatch.setattr(
        manager_module,
        "_CHANNEL_START_RETRY_MAX_DELAY",
        5.0,
    )
    channel = _FakeChannel(
        [
            _retryable_error(),
            _retryable_error(),
            _retryable_error(),
            _retryable_error(),
            None,
        ],
    )
    manager = ChannelManager([channel])

    await manager._start_channel(channel)

    assert sleep.await_args_list == [
        call(2.0),
        call(4.0),
        call(5.0),
        call(5.0),
    ]
    assert channel.start_attempts == 5
    assert channel.stop_attempts == 4


@pytest.mark.asyncio
async def test_non_retryable_startup_failure_is_not_retried() -> None:
    channel = _FakeChannel(
        [ChannelError(channel_name="test", message="invalid credentials")],
    )
    manager = ChannelManager([channel])

    await manager._start_channel(channel)

    assert channel.start_attempts == 1
    assert channel.stop_attempts == 1


@pytest.mark.asyncio
async def test_stop_all_cancels_pending_startup_retry(monkeypatch) -> None:
    monkeypatch.setattr(
        manager_module,
        "_CHANNEL_START_RETRY_INITIAL_DELAY",
        60.0,
    )
    channel = _FakeChannel([_retryable_error(), None])
    manager = ChannelManager([channel])

    await manager.start_all()
    await asyncio.wait_for(channel.first_attempt.wait(), timeout=1.0)
    await manager.stop_all()

    assert channel.start_attempts == 1
    assert not manager._start_tasks
