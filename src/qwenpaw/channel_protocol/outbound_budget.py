# -*- coding: utf-8 -*-
"""SDK-free total outbound effect budget, independent of RPC receipts."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
import inspect
import math

DEFAULT_SEND_TIMEOUT = 120.0
SEND_RECEIPT_MARGIN = 5.0
OUTBOUND_METHODS = frozenset(
    {
        "channel.send",
        "channel.reaction",
        "channel.response.open",
        "channel.response.prepare",
        "channel.response.finish",
    },
)
_deadline = ContextVar("channel_send_deadline", default=None)


def validate_send_timeout(value):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError("Send timeout must be finite and positive")
    return float(value)


def validate_send_timeouts(values):
    if not isinstance(values, Mapping) or any(
        not isinstance(key, str) or not key for key in values
    ):
        raise ValueError("Channel send timeouts must be a mapping")
    return {key: validate_send_timeout(value) for key, value in values.items()}


@contextmanager
def send_budget(seconds=DEFAULT_SEND_TIMEOUT):
    """Nested SDK stages inherit the same monotonic deadline."""
    deadline = asyncio.get_running_loop().time() + validate_send_timeout(
        seconds,
    )
    inherited = _deadline.get()
    token = _deadline.set(min(inherited, deadline) if inherited else deadline)
    try:
        yield
    finally:
        _deadline.reset(token)


def remaining_send_timeout():
    deadline = _deadline.get()
    if deadline is None:
        return None
    return max(0.0, deadline - asyncio.get_running_loop().time())


async def await_send(awaitable):
    """Bound the whole native await, preserving stricter SDK idle limits."""
    if remaining_send_timeout() == 0:
        if inspect.iscoroutine(awaitable):
            awaitable.close()
        raise TimeoutError("Channel send budget exhausted")
    async with asyncio.timeout_at(_deadline.get()):
        return await awaitable


def retry_delay_fits(delay):
    remaining = remaining_send_timeout()
    return (
        math.isfinite(delay)
        and delay >= 0
        and (remaining is None or delay < remaining)
    )
