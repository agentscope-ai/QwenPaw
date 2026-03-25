# -*- coding: utf-8 -*-
"""Global LLM request rate limiter.

How it works:
1. asyncio.Semaphore caps the number of concurrent in-flight LLM calls.
2. A global pause timestamp: when a 429 is received every subsequent
   acquire() waits until the pause expires, eliminating thundering-herd
   retries.
3. Per-waiter jitter: each caller adds a small random offset on top of
   the remaining pause time, so they spread out when waking up.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

logger = logging.getLogger(__name__)


class LLMRateLimiter:
    """Global LLM request rate limiter.

    Coroutine-safe: all mutable state is protected by an asyncio.Lock and
    is intended for use within a single event loop.
    """

    def __init__(
        self,
        max_concurrent: int = 3,
        default_pause_seconds: float = 5.0,
        jitter_range: float = 1.0,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._pause_until: float = 0.0
        self._lock = asyncio.Lock()
        self._default_pause = default_pause_seconds
        self._jitter_range = jitter_range

        # Own counter instead of reading semaphore._value (private API).
        self._in_flight: int = 0

        self._total_acquired: int = 0
        self._total_paused: int = 0
        self._total_rate_limited: int = 0

    async def acquire(self) -> None:
        """Acquire an execution permit.

        If a global pause is active, waits until it expires (plus a random
        jitter to stagger concurrent waiters), then competes for a semaphore
        slot.

        The while-loop re-checks the pause timestamp after each sleep because
        a new 429 may have arrived while we were waiting, extending the pause.
        The hard upper-bound is enforced by the asyncio.wait_for() timeout
        wrapping every acquire() call site in RetryChatModel.
        """
        while True:
            now = time.monotonic()
            remaining = self._pause_until - now
            if remaining <= 0:
                break
            jitter = random.uniform(0, self._jitter_range)
            wait_time = remaining + jitter
            self._total_paused += 1
            logger.debug(
                "LLM rate limiter: paused %.1fs (remaining=%.1fs + "
                "jitter=%.1fs)",
                wait_time,
                remaining,
                jitter,
            )
            await asyncio.sleep(wait_time)

        await self._semaphore.acquire()
        self._in_flight += 1
        self._total_acquired += 1

    def release(self) -> None:
        """Release the semaphore slot. Must be paired with a prior acquire(
        )."""
        self._in_flight -= 1
        self._semaphore.release()

    async def report_rate_limit(
        self,
        retry_after: float | None = None,
    ) -> None:
        """Record a 429 rate-limit response and set the global pause timestamp.

        Args:
            retry_after: Seconds from the API's Retry-After header.
                         Falls back to the configured default when None.
        """
        pause = retry_after if retry_after is not None else self._default_pause
        async with self._lock:
            new_until = time.monotonic() + pause
            if new_until > self._pause_until:
                self._pause_until = new_until
                self._total_rate_limited += 1
                logger.warning(
                    "LLM rate limiter: global pause set for %.1fs "
                    "(total_rate_limited=%d)",
                    pause,
                    self._total_rate_limited,
                )

    def stats(self) -> dict:
        """Return a snapshot of runtime statistics for logging or
        monitoring."""
        now = time.monotonic()
        return {
            "max_concurrent": self._max_concurrent,
            "current_in_flight": self._in_flight,
            "current_available": max(
                0,
                self._max_concurrent - self._in_flight,
            ),
            "is_paused": now < self._pause_until,
            "pause_remaining_s": max(0.0, self._pause_until - now),
            "total_acquired": self._total_acquired,
            "total_paused": self._total_paused,
            "total_rate_limited": self._total_rate_limited,
        }


# Global singleton
_global_limiter: LLMRateLimiter | None = None
_init_lock: asyncio.Lock | None = None


def _get_init_lock() -> asyncio.Lock:
    global _init_lock
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    return _init_lock


async def get_rate_limiter(
    max_concurrent: int | None = None,
    default_pause_seconds: float | None = None,
    jitter_range: float | None = None,
) -> LLMRateLimiter:
    """Return the global LLMRateLimiter singleton, lazily initialised (
    coroutine-safe).

    On the *first* call the provided values (or env-var constants as fallback)
    are used to construct the singleton.  All subsequent calls return the same
    instance regardless of the arguments passed.

    Args:
        max_concurrent: Cap on concurrent in-flight LLM calls.
        default_pause_seconds: Pause duration (s) applied on a 429 response.
        jitter_range: Random jitter (s) added on top of the pause.
    """
    global _global_limiter
    if _global_limiter is not None:
        return _global_limiter
    async with _get_init_lock():
        if _global_limiter is not None:
            return _global_limiter
        from ..constant import (
            LLM_MAX_CONCURRENT,
            LLM_RATE_LIMIT_JITTER,
            LLM_RATE_LIMIT_PAUSE,
        )

        resolved_max = (
            max_concurrent
            if max_concurrent is not None
            else LLM_MAX_CONCURRENT
        )
        resolved_pause = (
            default_pause_seconds
            if default_pause_seconds is not None
            else LLM_RATE_LIMIT_PAUSE
        )
        resolved_jitter = (
            jitter_range if jitter_range is not None else LLM_RATE_LIMIT_JITTER
        )

        _global_limiter = LLMRateLimiter(
            max_concurrent=resolved_max,
            default_pause_seconds=resolved_pause,
            jitter_range=resolved_jitter,
        )
        logger.info(
            "LLM rate limiter initialized: max_concurrent=%d, "
            "default_pause=%.1fs, jitter=%.1fs",
            resolved_max,
            resolved_pause,
            resolved_jitter,
        )
    return _global_limiter
