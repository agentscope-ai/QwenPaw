# -*- coding: utf-8 -*-
"""Event-loop isolation tests for the global LLM rate limiter registry."""

from __future__ import annotations

import asyncio

import pytest

from qwenpaw.providers.rate_limiter import (
    _limiters,
    get_rate_limiter,
)


@pytest.fixture(autouse=True)
def _clear_limiters():
    _limiters.clear()
    yield
    _limiters.clear()


def test_cross_loop_use_raises_instead_of_hanging() -> None:
    first = asyncio.new_event_loop()
    second = asyncio.new_event_loop()
    try:
        limiter = first.run_until_complete(
            get_rate_limiter("test:model"),
        )
        with pytest.raises(RuntimeError, match="different .*event loop"):
            second.run_until_complete(
                get_rate_limiter("test:model"),
            )
    finally:
        first.close()
        second.close()

    assert limiter.loop is first


def test_closed_loop_limiter_is_replaced() -> None:
    first = asyncio.new_event_loop()
    try:
        first.run_until_complete(get_rate_limiter("test:closed"))
    finally:
        first.close()

    second = asyncio.new_event_loop()
    try:
        replacement = second.run_until_complete(
            get_rate_limiter("test:closed"),
        )
    finally:
        second.close()

    assert replacement.loop is second
    # The stale limiter must not be reused from the closed loop.
    assert _limiters["test:closed"] is replacement


@pytest.mark.asyncio
async def test_same_loop_limiter_is_reused() -> None:
    first = await get_rate_limiter("test:same-loop")
    second = await get_rate_limiter("test:same-loop")
    assert first is second


@pytest.mark.asyncio
async def test_limiter_acquire_rejects_foreign_loop_binding() -> None:
    limiter = await get_rate_limiter("test:bind")
    other_loop = asyncio.new_event_loop()
    try:
        with pytest.raises(RuntimeError, match="different .*event loop"):
            limiter.bind_loop(other_loop)
    finally:
        other_loop.close()
