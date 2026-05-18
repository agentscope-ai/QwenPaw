# -*- coding: utf-8 -*-
"""Global LLM request rate limiter.

How it works:
1. QPM sliding window: tracks request timestamps in a 60-second window.
   Before each call, if the window is full, the caller waits until the
   oldest timestamp slides out — proactively preventing 429s.
2. asyncio.Semaphore caps the number of concurrent in-flight LLM calls.
3. A global pause timestamp: when a 429 is received every subsequent
   acquire() waits until the pause expires, eliminating thundering-herd
   retries.
4. Per-waiter jitter: each caller adds a small random offset on top of
   the remaining pause time, so they spread out when waking up.

acquire() execution order:
    wait for 429 cooldown → wait for QPM slot → wait for semaphore slot
"""

from __future__ import annotations

import asyncio
import collections
import logging
import random
import time

logger = logging.getLogger(__name__)


class LLMRateLimiter:
    """Global LLM request rate limiter.

    Coroutine-safe: all mutable state is protected by asyncio primitives and
    is intended for use within a single event loop.

    Args:
        max_concurrent: Maximum concurrent in-flight LLM calls (semaphore).
        max_qpm: Maximum queries per minute (sliding window). 0 = disabled.
        default_pause_seconds: Global pause duration on a 429 response.
        jitter_range: Random jitter (seconds) added on top of the pause.
    """

    def __init__(
        self,
        max_concurrent: int = 3,
        max_qpm: int = 0,
        default_pause_seconds: float = 5.0,
        jitter_range: float = 1.0,
    ) -> None:
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._pause_until: float = 0.0
        self._lock = asyncio.Lock()
        self._default_pause = default_pause_seconds
        self._jitter_range = jitter_range

        # QPM sliding window — stores monotonic timestamps of dispatched calls.
        self._max_qpm = max_qpm
        self._request_times: collections.deque[float] = collections.deque()
        self._qpm_lock = asyncio.Lock()

        # Own counter instead of reading semaphore._value (private API).
        self._in_flight: int = 0

        self._total_acquired: int = 0
        self._total_paused: int = 0
        self._total_qpm_waited: int = 0
        self._total_rate_limited: int = 0

    async def acquire(self) -> None:
        """Acquire an execution permit.

        Execution order:
        1. If a global 429 pause is active, wait until it expires (plus
           per-waiter jitter to avoid a new burst on wake-up).  The while-loop
           re-checks after each sleep because a new 429 may have extended the
           pause while we were waiting.
        2. If RPM limiting is enabled, wait until a slot opens in the 60-second
           sliding window, then record this call's timestamp.
        3. Acquire the semaphore slot (concurrency cap).

        The hard upper-bound timeout is enforced by asyncio.wait_for() at
        every call site in RetryChatModel.
        """
        # Step 1 — 429 cooldown.
        while True:
            now = time.monotonic()
            remaining = self._pause_until - now
            if remaining <= 0:
                break
            jitter = random.uniform(0, self._jitter_range)
            wait_time = remaining + jitter
            self._total_paused += 1
            logger.debug(
                "LLM rate limiter: 429 cooldown %.1fs "
                "(remaining=%.1fs + jitter=%.1fs)",
                wait_time,
                remaining,
                jitter,
            )
            await asyncio.sleep(wait_time)

        # Step 2 — QPM sliding window.
        if self._max_qpm > 0:
            await self._acquire_qpm_slot()

        # Step 3 — concurrency semaphore.
        await self._semaphore.acquire()
        self._in_flight += 1
        self._total_acquired += 1

    async def _acquire_qpm_slot(self) -> None:
        """Wait until the 60-second sliding window has room, then record the
        current timestamp to claim the slot.

        Under the qpm_lock we atomically prune expired entries, check capacity,
        and append the new timestamp.  If the window is full we compute the
        minimum wait time, release the lock, sleep, then retry.
        """
        while True:
            async with self._qpm_lock:
                now = time.monotonic()
                cutoff = now - 60.0
                # Evict timestamps that have slid out of the window.
                while self._request_times and self._request_times[0] < cutoff:
                    self._request_times.popleft()

                if len(self._request_times) < self._max_qpm:
                    # Slot available — record and return.
                    self._request_times.append(now)
                    return

                # Window full — compute how long until the oldest entry
                # expires.
                oldest = self._request_times[0]
                wait_time = oldest + 60.0 - now + 0.05  # 50 ms margin

            self._total_qpm_waited += 1
            logger.debug(
                "LLM QPM limit (%d/min) reached, waiting %.1fs for slot",
                self._max_qpm,
                wait_time,
            )
            await asyncio.sleep(wait_time)

    def release(self) -> None:
        """Release the semaphore slot.
        Must be paired with a prior acquire()."""
        self._in_flight -= 1
        self._semaphore.release()

    async def on_success(self) -> None:
        """Clear the global pause after a successful LLM call.

        A completed call proves the API's rate-limit window has ended.
        Resetting _pause_until lets subsequent callers proceed immediately
        instead of waiting out the remainder of a stale pause set by a
        previous 429 (e.g. from a background dream/cron task).
        """
        async with self._lock:
            if self._pause_until > 0:
                self._pause_until = 0.0
                logger.debug(
                    "LLM rate limiter: pause cleared after successful call",
                )

    # Maximum pause duration (seconds) honoured from any Retry-After header.
    # Prevents a single API 429 (e.g. retry_after=300 from DashScope) from
    # stalling all LLM calls — including interactive user chats — for minutes.
    # Background tasks (dream, heartbeat) share the global limiter, so without
    # this cap a single dream 429 can cascade into a 5-minute hang.
    _MAX_PAUSE_SECONDS: float = 60.0

    async def report_rate_limit(
        self,
        retry_after: float | None = None,
    ) -> None:
        """Record a 429 rate-limit response and set the global pause timestamp.

        Args:
            retry_after: Seconds from the API's Retry-After header.
                         Falls back to the configured default when None.
                         Always capped at ``_MAX_PAUSE_SECONDS`` so that a
                         large Retry-After from a background task cannot
                         stall interactive user requests for minutes.
        """
        raw_pause = (
            retry_after if retry_after is not None else self._default_pause
        )
        pause = min(raw_pause, self._MAX_PAUSE_SECONDS)
        if pause < raw_pause:
            logger.debug(
                "LLM rate limiter: capping retry_after %.1fs → %.1fs",
                raw_pause,
                pause,
            )
        async with self._lock:
            new_until = time.monotonic() + pause
            if new_until > self._pause_until:
                self._pause_until = new_until
                self._total_rate_limited += 1
                logger.warning(
                    "LLM rate limiter: global pause set for %.1fs "
                    "(raw_retry_after=%.1fs, total_rate_limited=%d)",
                    pause,
                    raw_pause,
                    self._total_rate_limited,
                )

    def stats(self) -> dict:
        """Return a snapshot of runtime statistics for logging or
        monitoring."""
        now = time.monotonic()
        cutoff = now - 60.0
        requests_last_60s = sum(1 for t in self._request_times if t >= cutoff)
        return {
            "max_concurrent": self._max_concurrent,
            "current_in_flight": self._in_flight,
            "current_available": max(
                0,
                self._max_concurrent - self._in_flight,
            ),
            "max_qpm": self._max_qpm,
            "requests_last_60s": requests_last_60s,
            "is_paused": now < self._pause_until,
            "pause_remaining_s": max(0.0, self._pause_until - now),
            "total_acquired": self._total_acquired,
            "total_paused": self._total_paused,
            "total_qpm_waited": self._total_qpm_waited,
            "total_rate_limited": self._total_rate_limited,
        }


# Per-model rate limiters keyed by "provider_id:model_name".
# Each model gets its own limiter so that a 429 from one provider/model
# (e.g. a dream cron using DashScope) does not stall user chats on a
# completely different provider (e.g. OpenRouter, Anthropic).
_limiters: dict[str, LLMRateLimiter] = {}
_limiters_lock: asyncio.Lock | None = None


def _get_limiters_lock() -> asyncio.Lock:
    global _limiters_lock
    if _limiters_lock is None:
        _limiters_lock = asyncio.Lock()
    return _limiters_lock


async def get_rate_limiter(
    limiter_key: str = "",
    max_concurrent: int | None = None,
    max_qpm: int | None = None,
    default_pause_seconds: float | None = None,
    jitter_range: float | None = None,
) -> LLMRateLimiter:
    """Return a per-model ``LLMRateLimiter``, lazily initialised
    (coroutine-safe).

    Each unique *limiter_key* (typically ``"provider_id:model_name"``) gets
    its own independent limiter instance.  A 429 on one model therefore does
    not pause calls to other models — background tasks (dream, heartbeat) that
    hit their quota limit can no longer stall interactive user chats on a
    different provider.

    On the *first* call for a given key the provided config values (or
    env-var constants as fallback) are used to construct the limiter.  All
    subsequent calls for the same key return the same instance regardless of
    the arguments passed.

    Args:
        limiter_key: Stable identifier for the limiter scope, e.g.
            ``"dashscope:qwen-plus"`` or
            ``"openrouter:nemotron-3-super-free"``.
            An empty string uses a shared fallback limiter.
        max_concurrent: Cap on concurrent in-flight LLM calls.
        max_qpm: Maximum queries per minute (sliding window). 0 = disabled.
        default_pause_seconds: Pause duration (s) applied on a 429 response.
        jitter_range: Random jitter (s) added on top of the pause.
    """
    if limiter_key in _limiters:
        return _limiters[limiter_key]
    async with _get_limiters_lock():
        if limiter_key in _limiters:
            return _limiters[limiter_key]
        from ..constant import (
            LLM_MAX_CONCURRENT,
            LLM_MAX_QPM,
            LLM_RATE_LIMIT_JITTER,
            LLM_RATE_LIMIT_PAUSE,
        )

        resolved_max = (
            max_concurrent
            if max_concurrent is not None
            else LLM_MAX_CONCURRENT
        )
        resolved_qpm = max_qpm if max_qpm is not None else LLM_MAX_QPM
        resolved_pause = (
            default_pause_seconds
            if default_pause_seconds is not None
            else LLM_RATE_LIMIT_PAUSE
        )
        resolved_jitter = (
            jitter_range if jitter_range is not None else LLM_RATE_LIMIT_JITTER
        )

        limiter = LLMRateLimiter(
            max_concurrent=resolved_max,
            max_qpm=resolved_qpm,
            default_pause_seconds=resolved_pause,
            jitter_range=resolved_jitter,
        )
        _limiters[limiter_key] = limiter
        logger.info(
            "LLM rate limiter initialized: key=%r max_concurrent=%d "
            "max_qpm=%d default_pause=%.1fs jitter=%.1fs",
            limiter_key,
            resolved_max,
            resolved_qpm,
            resolved_pause,
            resolved_jitter,
        )
    return limiter


def reset_rate_limiter(limiter_key: str | None = None) -> None:
    """Reset rate limiter(s) (for testing or service restart).

    Args:
        limiter_key: If given, reset only that key's limiter.
                     If ``None``, reset all limiters.
    """
    if limiter_key is not None:
        _limiters.pop(limiter_key, None)
    else:
        _limiters.clear()
