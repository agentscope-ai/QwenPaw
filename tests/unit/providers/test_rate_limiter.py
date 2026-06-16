# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import time

import pytest

from qwenpaw.providers.rate_limiter import LLMRateLimiter, _limiters


@pytest.fixture(autouse=True)
def _reset_global_limiters():
    """Ensure each test starts with a clean global limiter registry."""
    _limiters.clear()
    yield
    _limiters.clear()


# ---------------------------------------------------------------------------
# LLMRateLimiter — basic acquire / release / stats
# ---------------------------------------------------------------------------


async def test_acquire_release_cycle() -> None:
    limiter = LLMRateLimiter(max_concurrent=2, max_qpm=0)
    ts = await limiter.acquire()
    assert isinstance(ts, float)
    assert limiter.stats()["current_in_flight"] == 1
    limiter.release()
    assert limiter.stats()["current_in_flight"] == 0


async def test_stats_snapshot() -> None:
    limiter = LLMRateLimiter(max_concurrent=5, max_qpm=10)
    stats = limiter.stats()
    assert stats["max_concurrent"] == 5
    assert stats["max_qpm"] == 10
    assert stats["current_in_flight"] == 0
    assert stats["current_available"] == 5
    assert stats["total_acquired"] == 0
    assert stats["is_paused"] is False


async def test_acquire_increments_total() -> None:
    limiter = LLMRateLimiter(max_concurrent=3, max_qpm=0)
    await limiter.acquire()
    await limiter.acquire()
    assert limiter.stats()["total_acquired"] == 2
    assert limiter.stats()["current_in_flight"] == 2
    limiter.release()
    limiter.release()


# ---------------------------------------------------------------------------
# 429 cooldown — report_rate_limit / on_success
# ---------------------------------------------------------------------------


async def test_report_rate_limit_sets_pause() -> None:
    limiter = LLMRateLimiter(max_concurrent=1, max_qpm=0)
    await limiter.report_rate_limit(retry_after=2.0)
    stats = limiter.stats()
    assert stats["is_paused"] is True
    assert stats["pause_remaining_s"] > 0
    assert stats["total_rate_limited"] == 1


async def test_report_rate_limit_caps_at_max() -> None:
    limiter = LLMRateLimiter(max_concurrent=1, max_qpm=0)
    limiter.MAX_PAUSE_SECONDS = 5.0
    await limiter.report_rate_limit(retry_after=100.0)
    stats = limiter.stats()
    assert stats["pause_remaining_s"] <= 5.0 + 0.1


async def test_report_rate_limit_default_pause() -> None:
    limiter = LLMRateLimiter(
        max_concurrent=1,
        max_qpm=0,
        default_pause_seconds=3.0,
    )
    await limiter.report_rate_limit(retry_after=None)
    stats = limiter.stats()
    assert stats["is_paused"] is True
    assert stats["pause_remaining_s"] <= 3.0 + 0.1


async def test_on_success_clears_stale_pause() -> None:
    limiter = LLMRateLimiter(max_concurrent=1, max_qpm=0)
    acquired_at = time.monotonic() + 10
    limiter._pause_until = time.monotonic() - 1
    await limiter.on_success(acquired_at)
    assert limiter._pause_until == 0.0


async def test_on_success_keeps_fresh_pause() -> None:
    limiter = LLMRateLimiter(max_concurrent=1, max_qpm=0)
    acquired_at = time.monotonic() - 10
    limiter._pause_until = time.monotonic() + 100
    original = limiter._pause_until
    await limiter.on_success(acquired_at)
    assert limiter._pause_until == original


# ---------------------------------------------------------------------------
# QPM sliding window
# ---------------------------------------------------------------------------


async def test_qpm_records_timestamps() -> None:
    limiter = LLMRateLimiter(max_concurrent=10, max_qpm=5)
    for _ in range(3):
        await limiter.acquire()
        limiter.release()
    assert limiter.stats()["requests_last_60s"] == 3


async def test_qpm_zero_disables_window() -> None:
    limiter = LLMRateLimiter(max_concurrent=10, max_qpm=0)
    for _ in range(20):
        await limiter.acquire()
        limiter.release()
    assert len(limiter._request_times) == 0


# ---------------------------------------------------------------------------
# get_rate_limiter singleton
# ---------------------------------------------------------------------------


async def test_get_rate_limiter_returns_same_instance() -> None:
    from qwenpaw.providers.rate_limiter import get_rate_limiter

    limiter1 = await get_rate_limiter(limiter_key="test:model")
    limiter2 = await get_rate_limiter(limiter_key="test:model")
    assert limiter1 is limiter2


async def test_get_rate_limiter_different_keys() -> None:
    from qwenpaw.providers.rate_limiter import get_rate_limiter

    limiter_a = await get_rate_limiter(limiter_key="provider_a:model")
    limiter_b = await get_rate_limiter(limiter_key="provider_b:model")
    assert limiter_a is not limiter_b
