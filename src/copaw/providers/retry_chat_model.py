# -*- coding: utf-8 -*-
"""Retry wrapper for ChatModelBase instances.

Transparently retries LLM API calls on transient errors (rate-limit,
timeout, connection) with configurable exponential back-off.

Concurrency and rate-limit control (LLMRateLimiter):
- A global semaphore caps the number of concurrent in-flight LLM calls,
  preventing a burst of requests from hammering the upstream API.
- When a 429 is received every concurrent caller is paused for the same
  duration (plus per-caller jitter) before re-trying, eliminating the
  thundering-herd problem where multiple callers retry at the same instant.

Semaphore ownership rules:
- Non-streaming: __call__'s finally block always releases the slot
  (owns_semaphore stays True throughout).
- Streaming: ownership transfers to _consume_stream_with_slot the moment
  __call__ returns the generator.  owns_semaphore is set to False before
  the return so __call__'s finally skips the release.
  _consume_stream_with_slot releases after the first chunk arrives.
- Cancellation safety: the boolean flag `acquired` tracks whether the
  semaphore slot has actually been taken; the final block only releases
  when acquired is True, preventing a spurious release on CancelledError.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, AsyncGenerator

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from agentscope_runtime.engine.schemas.exception import (
    RateLimitExceededException,
)

from ..constant import (
    LLM_ACQUIRE_TIMEOUT,
    LLM_BACKOFF_BASE,
    LLM_BACKOFF_CAP,
    LLM_MAX_CONCURRENT,
    LLM_MAX_RETRIES,
    LLM_MAX_QPM,
    LLM_RATE_LIMIT_JITTER,
    LLM_RATE_LIMIT_PAUSE,
)
from .rate_limiter import LLMRateLimiter, get_rate_limiter

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504, 529}

_openai_retryable: tuple[type[Exception], ...] | None = None
_anthropic_retryable: tuple[type[Exception], ...] | None = None


@dataclass(frozen=True, slots=True)
class RetryConfig:
    """Retry policy for transient LLM API failures."""

    enabled: bool = LLM_MAX_RETRIES > 0
    max_retries: int = max(LLM_MAX_RETRIES, 1)
    backoff_base: float = LLM_BACKOFF_BASE
    backoff_cap: float = LLM_BACKOFF_CAP


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    """Rate-limiting policy for LLM calls.

    Controls the global LLMRateLimiter singleton that caps concurrency and
    coordinates pauses when a 429 is received.  The singleton is initialised
    on the *first* call; subsequent callers share the same instance.

    Attributes:
        max_concurrent: Maximum concurrent in-flight LLM calls.
        max_qpm: Maximum queries per minute (sliding window). 0 = disabled.
        pause_seconds: Global pause duration (s) on a 429 response.
        jitter_range: Random jitter (s) added on top of the pause.
        acquire_timeout: Max seconds to wait for a slot before raising.
    """

    max_concurrent: int = LLM_MAX_CONCURRENT
    max_qpm: int = LLM_MAX_QPM
    pause_seconds: float = LLM_RATE_LIMIT_PAUSE
    jitter_range: float = LLM_RATE_LIMIT_JITTER
    acquire_timeout: float = LLM_ACQUIRE_TIMEOUT


def _get_openai_retryable() -> tuple[type[Exception], ...]:
    global _openai_retryable
    if _openai_retryable is None:
        try:
            import openai

            _openai_retryable = (
                openai.RateLimitError,
                openai.APITimeoutError,
                openai.APIConnectionError,
            )
        except ImportError:
            _openai_retryable = ()
    return _openai_retryable


def _get_anthropic_retryable() -> tuple[type[Exception], ...]:
    global _anthropic_retryable
    if _anthropic_retryable is None:
        try:
            import anthropic

            _anthropic_retryable = (
                anthropic.RateLimitError,
                anthropic.APITimeoutError,
                anthropic.APIConnectionError,
            )
        except ImportError:
            _anthropic_retryable = ()
    return _anthropic_retryable


def _is_retryable(exc: Exception) -> bool:
    """Return *True* if *exc* should trigger a retry."""
    retryable = _get_openai_retryable() + _get_anthropic_retryable()
    if retryable and isinstance(exc, retryable):
        return True

    status = getattr(exc, "status_code", None)
    if status is not None and status in RETRYABLE_STATUS_CODES:
        return True

    return False


def _is_rate_limit(exc: Exception) -> bool:
    """Return *True* if *exc* is specifically a 429 rate-limit error."""
    return getattr(exc, "status_code", None) == 429


def _extract_retry_after(exc: Exception) -> float | None:
    """Parse the Retry-After header value (in seconds) from an exception.

    Handles both OpenAI and Anthropic SDK exception shapes, which expose
    headers either directly on the exception or on an attached response object.
    """
    headers = getattr(exc, "headers", None) or getattr(
        getattr(exc, "response", None),
        "headers",
        None,
    )
    if headers:
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
    return None


def _normalize_retry_config(retry_config: RetryConfig | None) -> RetryConfig:
    """Normalize externally supplied retry config into safe bounds."""
    if retry_config is None:
        return RetryConfig()
    normalized_backoff_base = max(0.1, retry_config.backoff_base)
    normalized_backoff_cap = max(
        0.5,
        retry_config.backoff_cap,
        normalized_backoff_base,
    )
    return RetryConfig(
        enabled=retry_config.enabled,
        max_retries=max(1, retry_config.max_retries),
        backoff_base=normalized_backoff_base,
        backoff_cap=normalized_backoff_cap,
    )


def _normalize_rate_limit_config(
    cfg: RateLimitConfig | None,
) -> RateLimitConfig:
    """Normalize externally supplied rate-limit config into safe bounds."""
    if cfg is None:
        return RateLimitConfig()
    return RateLimitConfig(
        max_concurrent=max(1, cfg.max_concurrent),
        max_qpm=max(0, cfg.max_qpm),
        pause_seconds=max(1.0, cfg.pause_seconds),
        jitter_range=max(0.0, cfg.jitter_range),
        acquire_timeout=max(10.0, cfg.acquire_timeout),
    )


def _compute_backoff(attempt: int, retry_config: RetryConfig) -> float:
    """Exponential back-off: base * 2^(attempt-1), capped."""
    return min(
        retry_config.backoff_cap,
        retry_config.backoff_base * (2 ** max(0, attempt - 1)),
    )


class RetryChatModel(ChatModelBase):
    """Transparent retry wrapper around any :class:`ChatModelBase`.

    The wrapper delegates every call to the underlying *inner* model and
    retries on transient errors with exponential back-off.  Streaming
    responses are also covered: if the stream fails mid-consumption the
    entire request is retried from scratch.

    A global LLMRateLimiter is consulted on every call to cap concurrency and
    to coordinate a shared pause across all callers when a 429 is received.
    """

    def __init__(
        self,
        inner: ChatModelBase,
        retry_config: RetryConfig | None = None,
        rate_limit_config: RateLimitConfig | None = None,
    ) -> None:
        super().__init__(model_name=inner.model_name, stream=inner.stream)
        self._inner = inner
        self._retry_config = _normalize_retry_config(retry_config)
        self._rate_limit_config = _normalize_rate_limit_config(
            rate_limit_config,
        )

    # Expose the real model's class so that formatter mapping keeps working
    # when code inspects ``model.__class__`` after wrapping.
    @property
    def inner_class(self) -> type:
        return self._inner.__class__

    async def _consume_stream_with_slot(
        self,
        stream: AsyncGenerator[ChatResponse, None],
        limiter: LLMRateLimiter,
    ) -> AsyncGenerator[ChatResponse, None]:
        """Yield all chunks from *stream*, managing the semaphore slot
        lifecycle.

        Releases the semaphore slot after the first chunk arrives — once the
        API starts streaming the request has been accepted and will not be
        rate-limited mid-flight, so holding the slot for the full streaming
        duration would unnecessarily starve other callers.

        Always closes *stream* on completion or error.  Any exception raised
        during iteration propagates to the caller's ``async for`` loop
        (i.e. _wrap_stream), which handles retry decisions.  The exception
        does not propagate to the final consumer unless all retries are
        exhausted.
        """
        first_chunk = True
        try:
            async for chunk in stream:
                if first_chunk:
                    first_chunk = False
                    # return the slot once the API starts delivering
                    limiter.release()
                yield chunk
        finally:
            await stream.aclose()
            if first_chunk:
                # Stream failed before producing any chunk;
                # slot not yet released.
                limiter.release()

    async def __call__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        limiter = await get_rate_limiter(
            max_concurrent=self._rate_limit_config.max_concurrent,
            max_qpm=self._rate_limit_config.max_qpm,
            default_pause_seconds=self._rate_limit_config.pause_seconds,
            jitter_range=self._rate_limit_config.jitter_range,
        )

        retries = (
            self._retry_config.max_retries if self._retry_config.enabled else 0
        )
        attempts = retries + 1
        last_exc: Exception | None = None

        # Find the actual underlying model to check if it's Gemini
        actual_model = self._inner
        while hasattr(actual_model, "_model"):
            actual_model = actual_model._model
            
        if actual_model.__class__.__name__ == "GeminiChatModel":
            from ..agents.utils.tool_message_utils import sanitize_gemini_messages, sanitize_gemini_tools
            
            new_args = list(args)
            new_kwargs = dict(kwargs)
            
            # Sanitize messages if passed as position 0
            if len(new_args) > 0 and isinstance(new_args[0], list):
                new_args[0] = sanitize_gemini_messages(new_args[0])
            elif "messages" in new_kwargs and isinstance(new_kwargs["messages"], list):
                new_kwargs["messages"] = sanitize_gemini_messages(new_kwargs["messages"])

            # Sanitize tools if passed as position 1
            if len(new_args) > 1 and new_args[1] is not None:
                new_args[1] = sanitize_gemini_tools(new_args[1])
            elif "tools" in new_kwargs and new_kwargs["tools"] is not None:
                new_kwargs["tools"] = sanitize_gemini_tools(new_kwargs["tools"])
                
            args = tuple(new_args)
            kwargs = new_kwargs

        for attempt in range(1, attempts + 1):
            # Acquire a semaphore slot, with a timeout to prevent
            # indefinite blocking. `acquired` tracks whether the slot was
            # taken so the final block can skip the release on
            # CancelledError (slot was never acquired).
            acquired = False
            owns_semaphore = True
            try:
                try:
                    await asyncio.wait_for(
                        limiter.acquire(),
                        timeout=self._rate_limit_config.acquire_timeout,
                    )
                    acquired = True
                except asyncio.TimeoutError as exc:
                    raise RateLimitExceededException(
                        operation="LLM execution",
                        retry_after=int(
                            self._rate_limit_config.acquire_timeout,
                        ),
                        details={
                            "reason": "Timed out waiting for execution slot",
                        },
                    ) from exc

                result = await self._inner(*args, **kwargs)

                if isinstance(result, AsyncGenerator):
                    # Transfer semaphore ownership to _wrap_stream, which uses
                    # _consume_stream_with_slot internally and handles
                    # retries on stream failure.
                    owns_semaphore = False
                    return self._wrap_stream(
                        result,
                        args,
                        kwargs,
                        attempt,
                        attempts,
                        limiter,
                    )

                return result

            except Exception as exc:
                last_exc = exc
                if _is_retryable(exc) and _is_rate_limit(exc):
                    await limiter.report_rate_limit(_extract_retry_after(exc))

                if not _is_retryable(exc) or attempt >= attempts:
                    raise

                delay = _compute_backoff(attempt, self._retry_config)
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s. "
                    "Retrying in %.1fs ...",
                    attempt,
                    attempts,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

            finally:
                if owns_semaphore and acquired:
                    limiter.release()

        # Should be unreachable, but satisfies the type-checker.
        raise last_exc  # type: ignore[misc]

    # pylint: disable=too-many-branches
    async def _wrap_stream(
        self,
        stream: AsyncGenerator[ChatResponse, None],
        call_args: tuple,
        call_kwargs: dict,
        current_attempt: int,
        max_attempts: int,
        limiter: LLMRateLimiter,
    ) -> AsyncGenerator[ChatResponse, None]:
        """Yield chunks from *stream*; on transient failure, retry the full
        request and yield from the new stream instead."""
        try:
            async for chunk in self._consume_stream_with_slot(stream, limiter):
                yield chunk
            return  # stream completed without error
        except Exception as failed_exc:
            if _is_retryable(failed_exc) and _is_rate_limit(failed_exc):
                await limiter.report_rate_limit(
                    _extract_retry_after(failed_exc),
                )

            if (
                not _is_retryable(failed_exc)
                or current_attempt >= max_attempts
            ):
                raise failed_exc

            delay = _compute_backoff(current_attempt, self._retry_config)
            logger.warning(
                "LLM stream failed (attempt %d/%d): %s. Retrying in %.1fs ...",
                current_attempt,
                max_attempts,
                failed_exc,
                delay,
            )
            await asyncio.sleep(delay)

        # Retry loop for stream failures
        for attempt in range(current_attempt + 1, max_attempts + 1):
            acquired = False
            owns_semaphore = True
            try:
                try:
                    await asyncio.wait_for(
                        limiter.acquire(),
                        timeout=self._rate_limit_config.acquire_timeout,
                    )
                    acquired = True
                except asyncio.TimeoutError as exc:
                    raise RateLimitExceededException(
                        operation="LLM execution (stream retry)",
                        retry_after=int(
                            self._rate_limit_config.acquire_timeout,
                        ),
                        details={
                            "reason": "Timed out waiting for execution slot",
                        },
                    ) from exc

                result = await self._inner(*call_args, **call_kwargs)

                if isinstance(result, AsyncGenerator):
                    owns_semaphore = False
                    try:
                        async for chunk in self._consume_stream_with_slot(
                            result,
                            limiter,
                        ):
                            yield chunk
                        return  # stream completed without error
                    except Exception as retry_failed:
                        if _is_retryable(retry_failed) and _is_rate_limit(
                            retry_failed,
                        ):
                            await limiter.report_rate_limit(
                                _extract_retry_after(retry_failed),
                            )
                        if (
                            not _is_retryable(retry_failed)
                            or attempt >= max_attempts
                        ):
                            raise retry_failed
                        retry_delay = _compute_backoff(
                            attempt,
                            self._retry_config,
                        )
                        logger.warning(
                            "LLM stream retry failed (attempt %d/%d): %s. "
                            "Retrying in %.1fs ...",
                            attempt,
                            max_attempts,
                            retry_failed,
                            retry_delay,
                        )
                        await asyncio.sleep(retry_delay)
                else:
                    yield result
                    return

            except Exception as retry_exc:
                if _is_retryable(retry_exc) and _is_rate_limit(retry_exc):
                    await limiter.report_rate_limit(
                        _extract_retry_after(retry_exc),
                    )
                if not _is_retryable(retry_exc) or attempt >= max_attempts:
                    raise
                retry_delay = _compute_backoff(attempt, self._retry_config)
                logger.warning(
                    "LLM stream retry failed (attempt %d/%d): %s. "
                    "Retrying in %.1fs ...",
                    attempt,
                    max_attempts,
                    retry_exc,
                    retry_delay,
                )
                await asyncio.sleep(retry_delay)

            finally:
                if owns_semaphore and acquired:
                    limiter.release()
