# -*- coding: utf-8 -*-
"""Retry wrapper for ChatModelBase instances.

Transparently retries LLM API calls on transient errors (rate-limit,
timeout, connection) with configurable exponential back-off.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, AsyncGenerator

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse

from ..constant import LLM_BACKOFF_BASE, LLM_BACKOFF_CAP, LLM_MAX_RETRIES

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


def _get_openai_retryable() -> tuple[type[Exception], ...]:
    global _openai_retryable  # noqa: PLW0603
    if _openai_retryable is None:
        try:
            import openai  # noqa: PLC0415

            _openai_retryable = (
                openai.RateLimitError,
                openai.APITimeoutError,
                openai.APIConnectionError,
            )
        except ImportError:
            _openai_retryable = ()
    return _openai_retryable


def _get_anthropic_retryable() -> tuple[type[Exception], ...]:
    global _anthropic_retryable  # noqa: PLW0603
    if _anthropic_retryable is None:
        try:
            import anthropic  # noqa: PLC0415

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
    """

    def __init__(
        self,
        inner: ChatModelBase,
        retry_config: RetryConfig | None = None,
    ) -> None:
        super().__init__(model_name=inner.model_name, stream=inner.stream)
        self._inner = inner
        self._retry_config = _normalize_retry_config(retry_config)

    # Expose the real model's class so that formatter mapping keeps working
    # when code inspects ``model.__class__`` after wrapping.
    @property
    def inner_class(self) -> type:
        return self._inner.__class__

    async def __call__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        retries = (
            self._retry_config.max_retries if self._retry_config.enabled else 0
        )
        attempts = retries + 1
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                result = await self._inner(*args, **kwargs)

                if isinstance(result, AsyncGenerator):
                    return self._wrap_stream(
                        result,
                        args,
                        kwargs,
                        attempt,
                        attempts,
                    )
                return result

            except Exception as exc:
                last_exc = exc
                if not _is_retryable(exc) or attempt >= attempts:
                    raise
                delay = _compute_backoff(attempt, self._retry_config)
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s. "
                    "Retrying in %.1fs …",
                    attempt,
                    attempts,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        # Should be unreachable, but satisfies the type-checker.
        raise last_exc  # type: ignore[misc]

    async def _wrap_stream(
        self,
        stream: AsyncGenerator[ChatResponse, None],
        call_args: tuple,
        call_kwargs: dict,
        current_attempt: int,
        max_attempts: int,
    ) -> AsyncGenerator[ChatResponse, None]:
        """Yield chunks from *stream*; on transient failure, retry the
        full request and yield from the new stream instead."""
        failed_exc: Exception | None = None
        try:
            async for chunk in stream:
                yield chunk
        except Exception as exc:
            failed_exc = exc
        finally:
            await stream.aclose()

        if failed_exc is None:
            return

        if not _is_retryable(failed_exc) or current_attempt >= max_attempts:
            raise failed_exc
        delay = _compute_backoff(current_attempt, self._retry_config)
        logger.warning(
            "LLM stream failed (attempt %d/%d): %s. Retrying in %.1fs …",
            current_attempt,
            max_attempts,
            failed_exc,
            delay,
        )
        await asyncio.sleep(delay)

        new_stream: AsyncGenerator | None = None
        for attempt in range(current_attempt + 1, max_attempts + 1):
            try:
                result = await self._inner(*call_args, **call_kwargs)
                if isinstance(result, AsyncGenerator):
                    new_stream = result
                    async for chunk in new_stream:
                        yield chunk
                    new_stream = None
                else:
                    yield result
                return
            except Exception as retry_exc:
                if new_stream is not None:
                    await new_stream.aclose()
                    new_stream = None
                if not _is_retryable(retry_exc) or attempt >= max_attempts:
                    raise
                retry_delay = _compute_backoff(
                    attempt,
                    self._retry_config,
                )
                logger.warning(
                    "LLM stream retry failed (attempt %d/%d): %s. "
                    "Retrying in %.1fs …",
                    attempt,
                    max_attempts,
                    retry_exc,
                    retry_delay,
                )
                await asyncio.sleep(retry_delay)
