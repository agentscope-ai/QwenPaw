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
from typing import Any, AsyncGenerator, AsyncIterator

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from qwenpaw.exceptions import (
    RateLimitExceededException,
)

from ..constant import (
    EnvVarLoader,
    LLM_ACQUIRE_TIMEOUT,
    LLM_BACKOFF_BASE,
    LLM_BACKOFF_CAP,
    LLM_MAX_CONCURRENT,
    LLM_MAX_RETRIES,
    LLM_MAX_QPM,
    LLM_RATE_LIMIT_JITTER,
    LLM_RATE_LIMIT_PAUSE,
)
from .error_utils import extract_status_code as _extract_status_code
from .model_capability_cache import get_capability_cache
from .model_error_policy import (
    is_retryable_same_model,
)
from .rate_limiter import LLMRateLimiter, get_rate_limiter
from .stream_progress import has_meaningful_stream_content

logger = logging.getLogger(__name__)

_STREAM_CLEANUP_TIMEOUT = 1.0
_STREAM_FIRST_CONTENT_TIMEOUT_ENV = "QWENPAW_LLM_STREAM_FIRST_CONTENT_TIMEOUT"
_STREAM_IDLE_TIMEOUT_ENV = "QWENPAW_LLM_STREAM_IDLE_TIMEOUT"
_pending_stream_cleanup_tasks: set[asyncio.Future[Any]] = set()
_pending_provider_cleanup_tasks_by_model: dict[
    str,
    set[asyncio.Future[Any]],
] = {}


def _track_stream_cleanup(
    task: asyncio.Future[Any],
    description: str,
) -> None:
    """Retain deferred cleanup work and report eventual failures."""
    _pending_stream_cleanup_tasks.add(task)

    def _on_done(completed: asyncio.Future[Any]) -> None:
        _pending_stream_cleanup_tasks.discard(completed)
        if completed.cancelled():
            return
        try:
            exc = completed.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.warning(f"Deferred {description} failed: {exc}")

    task.add_done_callback(_on_done)


@dataclass(slots=True)
class _StreamCleanupState:
    """Record whether stream cleanup was moved off the request path."""

    deferred: bool = False


class _AcquireTimeoutError(RateLimitExceededException):
    """Raised when ``limiter.acquire()`` times out internally.

    Distinct from a real API 429 so the retry loop can identify it via
    ``isinstance`` and raise immediately without calling
    ``report_rate_limit()`` or attempting another retry.
    """


class StreamIdleTimeoutError(TimeoutError):
    """Raised when an LLM stream stops producing content-bearing chunks."""

    def __init__(
        self,
        model_key: str,
        timeout_seconds: float,
        setting_name: str | None = None,
        cleanup_deferred: bool = False,
    ) -> None:
        self.model_key = model_key
        self.timeout_seconds = timeout_seconds
        self.cleanup_deferred = cleanup_deferred
        setting_hint = (
            f". Set {setting_name} to adjust this timeout"
            if setting_name
            else ""
        )
        super().__init__(
            f"LLM stream for {model_key} produced no content for "
            f"{timeout_seconds:g}s{setting_hint}",
        )


class StreamCleanupPendingError(TimeoutError):
    """Raised while a previous stream for the model is still cleaning up."""

    def __init__(self, model_key: str) -> None:
        self.model_key = model_key
        super().__init__(
            f"LLM stream cleanup for {model_key} is still in progress",
        )


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


def _is_retryable(exc: Exception) -> bool:
    """Return *True* if *exc* should trigger a retry."""
    if isinstance(exc, StreamCleanupPendingError):
        return False
    if isinstance(exc, StreamIdleTimeoutError) and exc.cleanup_deferred:
        return False
    return is_retryable_same_model(exc)


def _is_rate_limit(exc: Exception) -> bool:
    """Return *True* if *exc* is specifically a 429 rate-limit error."""
    return _extract_status_code(exc) == 429


def _is_missing_reasoning_content_error(exc: Exception) -> bool:
    """Return *True* if *exc* is a 400 about missing ``reasoning_content``.

    DeepSeek (and compatible providers) require every assistant message to
    carry ``reasoning_content`` when thinking mode is active.  When the
    conversation history was produced by a non-reasoning model, these
    fields are absent and the API rejects the request with a 400.
    """
    if _extract_status_code(exc) != 400:
        return False
    return "reasoning_content" in str(exc)


def _inject_reasoning_content(
    args: tuple,
    kwargs: dict[str, Any],
) -> bool:
    """Add ``reasoning_content = " "`` to assistant messages that lack it.

    Modifies the formatted message dicts **in-place** so the subsequent
    retry sees the updated values.  Returns *True* when at least one
    message was patched.
    """
    messages: list[dict] | None = kwargs.get("messages")
    if messages is None and args:
        candidate = args[0]
        if isinstance(candidate, list):
            messages = candidate

    if not messages:
        return False

    modified = False
    for msg in messages:
        if (
            isinstance(msg, dict)
            and msg.get("role") == "assistant"
            and "reasoning_content" not in msg
        ):
            msg["reasoning_content"] = " "
            modified = True

    return modified


def _enable_reasoning_content_fallback(
    model: Any,
    args: tuple,
    kwargs: dict[str, Any],
) -> bool:
    """Enable the missing-reasoning fallback at the correct call layer.

    Some callers pass already-formatted wire dictionaries, where the legacy
    in-place injector is sufficient.  AgentScope 2.0 passes ``Msg`` objects
    instead; those are formatted only inside the wrapped provider model, so
    adding a dictionary key here cannot work.  For that path, enable the
    formatter's request-time placeholder mode and let it preserve real
    reasoning while filling only missing assistant segments.

    Returns ``True`` when the fallback is available for this call.  An
    already-enabled formatter also returns ``True``: another concurrent call
    may have enabled it after this request was formatted but before its 400
    was handled, and that in-flight request still needs one retry.
    """
    if _inject_reasoning_content(args, kwargs):
        return True

    messages = kwargs.get("messages")
    if messages is None and args:
        messages = args[0] if isinstance(args[0], list) else None
    if not isinstance(messages, list) or not any(
        getattr(msg, "role", None) == "assistant" for msg in messages
    ):
        return False

    # RetryChatModel wraps TokenRecordingModelWrapper, which in turn wraps
    # the provider model.  Walk both conventional wrapper links without
    # depending on those concrete classes.
    pending = [model]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))

        formatter = getattr(current, "formatter", None)
        if formatter is not None and getattr(
            formatter,
            "_qwenpaw_supports_reasoning_content_fallback",
            False,
        ):
            if getattr(
                formatter,
                "_qwenpaw_require_reasoning_content",
                False,
            ):
                return True
            setattr(
                formatter,
                "_qwenpaw_require_reasoning_content",
                True,
            )
            return True

        for attr in ("_inner", "_model"):
            wrapped = getattr(current, attr, None)
            if wrapped is not None:
                pending.append(wrapped)

    return False


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
        stream_first_content_timeout: float | None = None,
        stream_idle_timeout: float | None = None,
    ) -> None:
        # agentscope 2.0 ChatModelBase requires credential/model/parameters;
        # forward the inner wrapper's own values so attribute access stays
        # transparent.
        super().__init__(
            credential=getattr(inner, "credential", None),
            model=getattr(inner, "model", "unknown"),
            parameters=getattr(inner, "parameters", None)
            or ChatModelBase.Parameters(),
            stream=getattr(inner, "stream", True),
            context_size=getattr(inner, "context_size", 32768),
        )
        self._inner = inner
        # AgentScope 2.0.6 reads the formatter from the outermost model
        # wrapper while normalizing incoming messages.  Keep this retry
        # layer transparent just like the model metadata forwarded above.
        formatter = getattr(inner, "formatter", None)
        if formatter is not None:
            self.formatter = formatter
        self._retry_config = _normalize_retry_config(retry_config)
        self._rate_limit_config = _normalize_rate_limit_config(
            rate_limit_config,
        )
        self._stream_idle_timeout_override = stream_idle_timeout
        self._stream_first_content_timeout_override = (
            stream_first_content_timeout
        )
        self._pending_provider_cleanup_tasks: set[asyncio.Future[Any]] = set()

    @property
    def formatter(self) -> Any:
        """Expose the wrapped model's formatter to AgentScope."""
        return self._inner.formatter

    @formatter.setter
    def formatter(self, value: Any) -> None:
        """Keep formatter updates synchronized with the wrapped model."""
        self._inner.formatter = value

    # Expose the real model's class so that formatter mapping keeps working
    # when code inspects ``model.__class__`` after wrapping.
    @property
    def inner_class(self) -> type:
        return self._inner.__class__

    @property
    def model_key(self) -> str:
        """Stable key for the underlying model: ``provider_id:model_name``."""
        provider_id = getattr(self._inner, "_provider_id", None)
        name = self._inner.model
        return f"{provider_id}:{name}" if provider_id else name

    def _track_provider_cleanup(
        self,
        task: asyncio.Future[Any],
        description: str,
    ) -> None:
        """Quarantine this model until deferred cleanup finishes."""
        model_key = self.model_key
        self._pending_provider_cleanup_tasks.add(task)
        model_tasks = _pending_provider_cleanup_tasks_by_model.setdefault(
            model_key,
            set(),
        )
        model_tasks.add(task)

        def _clear_quarantine(completed: asyncio.Future[Any]) -> None:
            self._pending_provider_cleanup_tasks.discard(completed)
            model_tasks.discard(completed)
            if not model_tasks:
                _pending_provider_cleanup_tasks_by_model.pop(model_key, None)

        task.add_done_callback(_clear_quarantine)
        _track_stream_cleanup(task, description)

    def _ensure_provider_available(self) -> None:
        """Reject upstream calls while old cleanup is still active."""
        if _pending_provider_cleanup_tasks_by_model.get(self.model_key):
            raise StreamCleanupPendingError(self.model_key)

    @staticmethod
    async def _handle_rate_limit_exc(
        exc: Exception,
        limiter: LLMRateLimiter,
    ) -> None:
        """Inspect *exc* and update the rate limiter accordingly.

        - Internal acquire timeout (``_AcquireTimeoutError``): re-raise as-is;
          no report, no retry.
        - Retryable API 429 with Retry-After > ``MAX_PAUSE_SECONDS``: re-raise
          immediately — retrying after the capped pause would just get another
          429 (e.g. Anthropic FreeUsageLimitError with Retry-After: 51496 s).
        - Normal 429: call ``report_rate_limit()`` to set the per-model pause.
        """
        if isinstance(exc, _AcquireTimeoutError):
            raise exc
        if _is_retryable(exc) and _is_rate_limit(exc):
            retry_after = _extract_retry_after(exc)
            if (
                retry_after is not None
                and retry_after > LLMRateLimiter.MAX_PAUSE_SECONDS
            ):
                raise exc
            await limiter.report_rate_limit(retry_after)

    async def _consume_stream_with_slot(
        self,
        stream: AsyncGenerator[ChatResponse, None],
        limiter: LLMRateLimiter,
        acquired_at: float,
    ) -> AsyncGenerator[ChatResponse, None]:
        """Yield chunks while managing the slot and upstream idle budget.

        Releases the semaphore slot after the first chunk arrives — once the
        API starts streaming the request has been accepted and will not be
        rate-limited mid-flight, so holding the slot for the full streaming
        duration would unnecessarily starve other callers.

        Before any content arrives, the first-content budget applies. After
        the first content-bearing chunk, the shorter steady-state idle budget
        applies and is restored by each later content-bearing chunk. Empty
        control chunks do not restore either budget. Both budgets count only
        time spent waiting for the upstream iterator, excluding time suspended
        at ``yield`` because of consumer backpressure. A configured timeout of
        zero disables that phase's watchdog.

        Attempts to close *stream* within a bounded cleanup period on
        completion or error. Non-cooperative cleanup continues in the
        background. Any iteration exception propagates to _wrap_stream,
        which handles retry decisions, and reaches the final consumer only
        after all retries are exhausted.

        Args:
            acquired_at: Timestamp from ``limiter.acquire()``, forwarded to
                ``on_success()`` so only stale pauses are cleared.
        """
        first_chunk = True
        loop = asyncio.get_running_loop()
        first_content_timeout = (
            max(0.0, float(self._stream_first_content_timeout_override))
            if self._stream_first_content_timeout_override is not None
            else EnvVarLoader.get_float(
                _STREAM_FIRST_CONTENT_TIMEOUT_ENV,
                30.0,
                min_value=0.0,
            )
        )
        idle_timeout = (
            max(0.0, float(self._stream_idle_timeout_override))
            if self._stream_idle_timeout_override is not None
            else EnvVarLoader.get_float(
                _STREAM_IDLE_TIMEOUT_ENV,
                30.0,
                min_value=0.0,
            )
        )
        active_timeout = first_content_timeout
        timeout_setting = _STREAM_FIRST_CONTENT_TIMEOUT_ENV
        idle_budget = active_timeout
        iterator = stream.__aiter__()
        cleanup_state = _StreamCleanupState()
        try:
            while True:
                wait_started_at = loop.time()
                try:
                    chunk = await self._next_stream_chunk(
                        iterator,
                        stream,
                        cleanup_state,
                        idle_budget if active_timeout > 0 else None,
                        active_timeout,
                        timeout_setting,
                    )
                except StopAsyncIteration:
                    break

                if active_timeout > 0:
                    idle_budget = max(
                        0.0,
                        idle_budget - (loop.time() - wait_started_at),
                    )

                if first_chunk:
                    first_chunk = False
                    # return the slot once the API starts delivering
                    limiter.release()
                    # streaming success: clear any stale 429 pause so
                    # subsequent callers (including user chats) are not
                    # held back by a pause set by a background task.
                    await limiter.on_success(acquired_at)
                if has_meaningful_stream_content(chunk.content):
                    active_timeout = idle_timeout
                    timeout_setting = _STREAM_IDLE_TIMEOUT_ENV
                    idle_budget = active_timeout
                is_last = bool(getattr(chunk, "is_last", False))
                yield chunk
                if is_last:
                    return
        finally:
            try:
                if not cleanup_state.deferred:
                    await self._close_stream_bounded(stream)
            finally:
                if first_chunk:
                    # Stream failed before producing any chunk;
                    # slot not yet released.
                    limiter.release()

    async def _next_stream_chunk(
        self,
        iterator: AsyncIterator[ChatResponse],
        stream: AsyncGenerator[ChatResponse, None],
        cleanup_state: _StreamCleanupState,
        timeout: float | None,
        timeout_seconds: float,
        timeout_setting: str,
    ) -> ChatResponse:
        """Return the next stream chunk within the upstream idle budget."""
        # Do not replace this with asyncio.wait_for(). AgentScope may suppress
        # CancelledError and return an interrupted response. Waiting on an
        # independent task lets this layer enforce its own timeout even when
        # the provider converts cancellation into a normal result.
        next_chunk = asyncio.ensure_future(anext(iterator))
        try:
            done, _ = await asyncio.wait(
                {next_chunk},
                timeout=timeout,
            )
        except BaseException:
            await self._cancel_stream_read(
                next_chunk,
                stream,
                cleanup_state,
            )
            raise

        if done:
            return next_chunk.result()

        cleanup_deferred = await self._cancel_stream_read(
            next_chunk,
            stream,
            cleanup_state,
        )
        raise StreamIdleTimeoutError(
            self.model_key,
            timeout_seconds,
            timeout_setting,
            cleanup_deferred=cleanup_deferred,
        )

    async def _cancel_stream_read(
        self,
        next_chunk: asyncio.Future[ChatResponse],
        stream: AsyncGenerator[ChatResponse, None],
        cleanup_state: _StreamCleanupState,
    ) -> bool:
        """Cancel one read without blocking the request indefinitely."""
        next_chunk.cancel()
        done, _ = await asyncio.wait(
            {next_chunk},
            timeout=_STREAM_CLEANUP_TIMEOUT,
        )
        if done:
            await asyncio.gather(next_chunk, return_exceptions=True)
            return False

        cleanup_state.deferred = True
        cleanup_task = asyncio.create_task(
            self._finish_stream_cleanup(next_chunk, stream),
        )
        self._track_provider_cleanup(
            cleanup_task,
            f"stream cleanup for {self.model_key}",
        )
        logger.warning(
            f"Stream read for {self.model_key} ignored cancellation for "
            f"{_STREAM_CLEANUP_TIMEOUT:g}s; cleanup continues in the "
            f"background",
        )
        return True

    async def _finish_stream_cleanup(
        self,
        next_chunk: asyncio.Future[ChatResponse],
        stream: AsyncGenerator[ChatResponse, None],
    ) -> None:
        """Close a stream after its non-cooperative read eventually exits."""
        await asyncio.gather(next_chunk, return_exceptions=True)
        await self._close_stream_bounded(stream)

    async def _close_stream_bounded(
        self,
        stream: AsyncGenerator[ChatResponse, None],
    ) -> None:
        """Close a provider stream without blocking the request forever."""
        close_task = asyncio.ensure_future(stream.aclose())
        try:
            done, _ = await asyncio.wait(
                {close_task},
                timeout=_STREAM_CLEANUP_TIMEOUT,
            )
        except BaseException:
            self._track_provider_cleanup(
                close_task,
                f"stream close for {self.model_key}",
            )
            raise

        if not done:
            self._track_provider_cleanup(
                close_task,
                f"stream close for {self.model_key}",
            )
            logger.warning(
                f"Stream close for {self.model_key} exceeded "
                f"{_STREAM_CLEANUP_TIMEOUT:g}s; cleanup continues in the "
                f"background",
            )
            return

        results = await asyncio.gather(
            close_task,
            return_exceptions=True,
        )
        if results and isinstance(results[0], BaseException):
            logger.warning(
                f"Stream close for {self.model_key} failed: {results[0]}",
            )

    async def generate_structured_output(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        limiter = await get_rate_limiter(
            limiter_key=self.model_key,
            max_concurrent=self._rate_limit_config.max_concurrent,
            max_qpm=self._rate_limit_config.max_qpm,
            default_pause_seconds=self._rate_limit_config.pause_seconds,
            jitter_range=self._rate_limit_config.jitter_range,
        )
        retries = (
            self._retry_config.max_retries if self._retry_config.enabled else 0
        )
        attempts = retries + 1

        for attempt in range(1, attempts + 1):
            acquired = False
            try:
                self._ensure_provider_available()
                try:
                    acquired_at = await asyncio.wait_for(
                        limiter.acquire(),
                        timeout=self._rate_limit_config.acquire_timeout,
                    )
                    acquired = True
                except asyncio.TimeoutError as exc:
                    raise _AcquireTimeoutError(
                        operation=(
                            f"LLM structured output for {self.model_key}"
                        ),
                        retry_after=int(
                            self._rate_limit_config.acquire_timeout,
                        ),
                        details={
                            "reason": (
                                f"Timed out waiting for {self.model_key} "
                                f"execution slot"
                            ),
                        },
                    ) from exc

                self._ensure_provider_available()
                result = await self._inner.generate_structured_output(
                    *args,
                    **kwargs,
                )
                await limiter.on_success(acquired_at)
                return result
            except Exception as exc:
                await self._handle_rate_limit_exc(exc, limiter)
                if not _is_retryable(exc) or attempt >= attempts:
                    raise
                delay = _compute_backoff(attempt, self._retry_config)
                logger.warning(
                    f"LLM structured output failed "
                    f"(attempt {attempt}/{attempts}): {exc}. "
                    f"Retrying in {delay:.1f}s ...",
                )
                await asyncio.sleep(delay)
            finally:
                if acquired:
                    limiter.release()

        raise RuntimeError(
            f"Structured output retry loop exhausted for {self.model_key}",
        )

    async def __call__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        cache = get_capability_cache()
        key = self.model_key

        if cache.get(key, "needs_reasoning_content", False):
            _enable_reasoning_content_fallback(self, args, kwargs)

        # Each model gets its own rate limiter keyed by
        # "provider_id:model_name" so that a 429 on one model (e.g. from a
        # dream/cron task) cannot stall user chats on a different provider.
        limiter = await get_rate_limiter(
            limiter_key=self.model_key,
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

        for attempt in range(1, attempts + 1):
            # Acquire a semaphore slot, with a timeout to prevent
            # indefinite blocking. `acquired` tracks whether the slot was
            # taken so the final block can skip the release on
            # CancelledError (slot was never acquired).
            acquired = False
            owns_semaphore = True
            acquired_at: float = 0.0
            try:
                self._ensure_provider_available()
                try:
                    acquired_at = await asyncio.wait_for(
                        limiter.acquire(),
                        timeout=self._rate_limit_config.acquire_timeout,
                    )
                    acquired = True
                except asyncio.TimeoutError as exc:
                    # Internal acquire timeout — NOT an API 429.
                    # _AcquireTimeoutError is a typed subclass so the outer
                    # handler can use isinstance() instead of a sentinel attr.
                    raise _AcquireTimeoutError(
                        operation="LLM execution",
                        retry_after=int(
                            self._rate_limit_config.acquire_timeout,
                        ),
                        details={
                            "reason": "Timed out waiting for execution slot",
                        },
                    ) from exc

                self._ensure_provider_available()
                try:
                    result = await self._inner(*args, **kwargs)
                except Exception as inner_exc:
                    if not (
                        _is_missing_reasoning_content_error(inner_exc)
                        and _enable_reasoning_content_fallback(
                            self,
                            args,
                            kwargs,
                        )
                    ):
                        raise
                    cache.learn(key, "needs_reasoning_content", True)
                    logger.warning(
                        "Thinking-mode model requires reasoning_content "
                        "on every assistant message. Injecting empty "
                        "values and retrying (learned for future calls).",
                    )
                    self._ensure_provider_available()
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
                        acquired_at,
                    )

                # Non-streaming success: clear any stale rate-limit pause so
                # subsequent callers are not held back by a pause set by an
                # unrelated background task (e.g. dream/cron 429).
                await limiter.on_success(acquired_at)
                return result

            except Exception as exc:
                last_exc = exc
                await self._handle_rate_limit_exc(exc, limiter)

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
        acquired_at: float = 0.0,
    ) -> AsyncGenerator[ChatResponse, None]:
        """Yield chunks from *stream*; on transient failure, retry the full
        request and yield from the new stream instead.

        Args:
            acquired_at: Timestamp from ``limiter.acquire()``, forwarded to
                ``on_success()`` so stale pauses are cleared but fresh ones
                (set by a concurrent 429 after this call acquired) are kept.
        """
        attempt = current_attempt
        pending_stream: AsyncGenerator[ChatResponse, None] | None = stream
        pending_acquired_at = acquired_at
        reasoning_injected = False
        emitted = False

        while True:
            try:
                if pending_stream is not None:
                    active_stream = self._consume_stream_with_slot(
                        pending_stream,
                        limiter,
                        pending_acquired_at,
                    )
                    try:
                        async for chunk in active_stream:
                            emitted = emitted or (
                                has_meaningful_stream_content(chunk.content)
                            )
                            yield chunk
                    finally:
                        await active_stream.aclose()
                    return  # stream completed without error

                acquired = False
                owns_semaphore = True
                retry_acquired_at: float = 0.0
                try:
                    self._ensure_provider_available()
                    try:
                        retry_acquired_at = await asyncio.wait_for(
                            limiter.acquire(),
                            timeout=self._rate_limit_config.acquire_timeout,
                        )
                        acquired = True
                    except asyncio.TimeoutError as exc:
                        raise _AcquireTimeoutError(
                            operation="LLM execution (stream retry)",
                            retry_after=int(
                                self._rate_limit_config.acquire_timeout,
                            ),
                            details={
                                "reason": (
                                    "Timed out waiting for execution slot"
                                ),
                            },
                        ) from exc

                    self._ensure_provider_available()
                    result = await self._inner(*call_args, **call_kwargs)

                    if isinstance(result, AsyncGenerator):
                        owns_semaphore = False
                        pending_stream = result
                        pending_acquired_at = retry_acquired_at
                        continue

                    yield result
                    return
                finally:
                    if owns_semaphore and acquired:
                        limiter.release()

            except Exception as retry_exc:
                pending_stream = None
                if emitted:
                    raise
                if (
                    not reasoning_injected
                    and _is_missing_reasoning_content_error(retry_exc)
                    and _enable_reasoning_content_fallback(
                        self,
                        call_args,
                        call_kwargs,
                    )
                ):
                    reasoning_injected = True
                    get_capability_cache().learn(
                        self.model_key,
                        "needs_reasoning_content",
                        True,
                    )
                    logger.warning(
                        "Thinking-mode stream requires reasoning_content "
                        "on every assistant message. Injecting empty "
                        "values and retrying (learned for future calls).",
                    )
                    continue

                await self._handle_rate_limit_exc(retry_exc, limiter)

                if not _is_retryable(retry_exc) or attempt >= max_attempts:
                    raise

                retry_delay = _compute_backoff(attempt, self._retry_config)
                logger.warning(
                    "LLM stream failed (attempt %d/%d): %s. "
                    "Retrying in %.1fs ...",
                    attempt,
                    max_attempts,
                    retry_exc,
                    retry_delay,
                )
                await asyncio.sleep(retry_delay)
                attempt += 1
