# -*- coding: utf-8 -*-
"""Fallback wrapper for ChatModelBase instances.

Transparently switches to backup models when the primary model fails due to
rate limits, timeouts, or service errors — all while preserving conversation
context.

Configuration via agent config or global config:
    {
        "fallback_config": {
            "fallbacks": [
                {"provider_id": "anthropic", "model": "claude-sonnet-4-6"},
                {"provider_id": "openai", "model": "gpt-4o-mini"}
            ],
            "cooldown_enabled": true,
            "max_fallbacks": 3
        }
    }
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncGenerator,
    Dict,
    List,
    Optional,
    Tuple,
)

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse

from .models import ModelFallbackConfig, ModelSlotConfig

if TYPE_CHECKING:
    from .provider_manager import ProviderManager

logger = logging.getLogger(__name__)

# Pre-compiled regex for status code extraction from error messages
_STATUS_CODE_RE = re.compile(r"\b([4-5]\d{2})\b")


class FailoverReason(Enum):
    """Classification of errors that may trigger fallback."""

    RATE_LIMIT = "rate_limit"  # 429 Too Many Requests
    TIMEOUT = "timeout"  # 408, 504 Request Timeout
    CONNECTION = "connection"  # 502 Bad Gateway
    OVERLOADED = "overloaded"  # 503, 529 Service Unavailable
    BILLING = "billing"  # 402 Payment Required
    AUTH = "auth"  # 401 Unauthorized
    CONTEXT_OVERFLOW = "context_overflow"  # 400 Context length exceeded
    ABORT = "abort"  # User aborted
    UNKNOWN = "unknown"  # Unclassified error


# HTTP status code to failover reason mapping
STATUS_CODE_MAP: Dict[int, FailoverReason] = {
    429: FailoverReason.RATE_LIMIT,
    408: FailoverReason.TIMEOUT,
    504: FailoverReason.TIMEOUT,
    502: FailoverReason.CONNECTION,
    503: FailoverReason.OVERLOADED,
    529: FailoverReason.OVERLOADED,
    401: FailoverReason.AUTH,
    402: FailoverReason.BILLING,
}

# Error messages that indicate context overflow
CONTEXT_OVERFLOW_INDICATORS = [
    "context length exceeded",
    "context_length_exceeded",
    "maximum context length",
    "token limit exceeded",
    "too many tokens",
    "input is too long",
]

# Transient errors that should trigger cooldown
TRANSIENT_ERRORS = {
    FailoverReason.RATE_LIMIT,
    FailoverReason.TIMEOUT,
    FailoverReason.CONNECTION,
    FailoverReason.OVERLOADED,
}

# Auth/billing errors that trigger longer cooldown
AUTH_BILLING_ERRORS = {
    FailoverReason.AUTH,
    FailoverReason.BILLING,
}

# Non-recoverable errors that should NOT trigger fallback
NON_RECOVERABLE_ERRORS = {
    FailoverReason.CONTEXT_OVERFLOW,
    FailoverReason.ABORT,
}

# Exponential backoff minutes for transient errors (1min, 5min, 25min, 60min)
TRANSIENT_BACKOFF_MINUTES = [1, 5, 25, 60]

# Exponential backoff hours for auth/billing errors (5h, 10h, 20h, 24h)
AUTH_BILLING_BACKOFF_HOURS = [5, 10, 20, 24]


class FallbackExhaustedError(Exception):
    """Raised when all fallback candidates have been exhausted."""

    def __init__(
        self,
        attempts: List[Dict[str, Any]],
        message: Optional[str] = None,
    ):
        self.attempts = attempts
        self.attempt_count = len(attempts)
        if message is None:
            providers = [a["provider"] for a in attempts]
            message = (
                f"All {self.attempt_count} model candidates failed: "
                f"{', '.join(providers)}"
            )
        super().__init__(message)


# pylint: disable=too-many-branches,too-many-return-statements
def _classify_error(exc: Exception) -> FailoverReason:
    """Classify an exception into a FailoverReason.

    Priority:
        1. HTTP status code (most reliable across SDK versions)
        2. Exception class name (for SDK-specific errors)
        3. Error message content (for context overflow, abort)

    Args:
        exc: The exception to classify

    Returns:
        FailoverReason enum value
    """
    exc_type_name = type(exc).__name__
    exc_str = str(exc).lower()

    # Priority 1: HTTP status code (most reliable across SDK versions)
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        status_code = getattr(exc, "code", None)
    if status_code is None:
        match = _STATUS_CODE_RE.search(str(exc))
        if match:
            try:
                status_code = int(match.group(1))
            except ValueError:
                pass

    if status_code and status_code in STATUS_CODE_MAP:
        return STATUS_CODE_MAP[status_code]

    # Priority 2: Exception class name (SDK-specific errors)
    if "RateLimitError" in exc_type_name:
        return FailoverReason.RATE_LIMIT
    elif "Timeout" in exc_type_name or "APITimeoutError" in exc_type_name:
        return FailoverReason.TIMEOUT
    elif (
        "ConnectionError" in exc_type_name
        or "APIConnectionError" in exc_type_name
    ):
        return FailoverReason.CONNECTION
    elif "AuthenticationError" in exc_type_name:
        return FailoverReason.AUTH

    # Priority 3: Error message content
    for indicator in CONTEXT_OVERFLOW_INDICATORS:
        if indicator in exc_str:
            return FailoverReason.CONTEXT_OVERFLOW

    # Check for abort/cancellation
    if (
        "abort" in exc_str
        or "cancel" in exc_str
        or "user interrupted" in exc_str
    ):
        return FailoverReason.ABORT

    return FailoverReason.UNKNOWN


@dataclass
class CooldownState:
    """Tracks cooldown state for a provider.

    Implements window immutability: once a cooldown is set, repeated failures
    within the window don't extend it. Error counters reset after cooldown
    window expires.
    """

    provider_id: str
    cooldown_until: Optional[float] = None
    error_count: int = 0
    last_failure_at: Optional[float] = None
    disabled_until: Optional[float] = None  # For auth/billing errors

    def is_in_cooldown(self, now: float) -> bool:
        """Check if provider is currently in cooldown.

        Args:
            now: Current timestamp

        Returns:
            True if provider should not be used
        """
        if self.disabled_until is not None and now < self.disabled_until:
            return True
        if self.cooldown_until is not None and now < self.cooldown_until:
            return True
        return False

    def record_failure(
        self,
        now: float,
        reason: FailoverReason,
    ) -> None:
        """Record a failure and update cooldown state.

        Implements window immutability: if already in cooldown, the window
        is not extended. Otherwise, calculates new cooldown based on error
        count with exponential backoff.

        Args:
            now: Current timestamp
            reason: Classification of the error
        """
        self.last_failure_at = now

        # Check if we should reset error count (cooldown expired)
        if self.cooldown_until is not None and now >= self.cooldown_until:
            self.error_count = 0
            self.cooldown_until = None

        if self.disabled_until is not None and now >= self.disabled_until:
            self.disabled_until = None

        # Window immutability: don't extend existing cooldown
        if self.is_in_cooldown(now):
            logger.debug(
                "Provider %s already in cooldown, not extending window",
                self.provider_id,
            )
            return

        self.error_count += 1

        # Calculate cooldown based on error type
        if reason in AUTH_BILLING_ERRORS:
            # Auth/billing: longer cooldown (hours)
            idx = min(
                self.error_count - 1,
                len(AUTH_BILLING_BACKOFF_HOURS) - 1,
            )
            hours = AUTH_BILLING_BACKOFF_HOURS[idx]
            self.disabled_until = now + (hours * 3600)
            logger.warning(
                "Provider %s disabled for %d hours due to %s (error #%d)",
                self.provider_id,
                hours,
                reason.value,
                self.error_count,
            )
        elif reason in TRANSIENT_ERRORS:
            # Transient errors: shorter cooldown (minutes)
            idx = min(self.error_count - 1, len(TRANSIENT_BACKOFF_MINUTES) - 1)
            minutes = TRANSIENT_BACKOFF_MINUTES[idx]
            self.cooldown_until = now + (minutes * 60)
            logger.warning(
                "Provider %s in cooldown for %d minutes due to %s (error #%d)",
                self.provider_id,
                minutes,
                reason.value,
                self.error_count,
            )
        else:
            # Unknown/other errors: minimal cooldown (1 minute)
            self.cooldown_until = now + 60
            logger.debug(
                "Provider %s in cooldown for 1 minute due to %s",
                self.provider_id,
                reason.value,
            )

    def record_success(self, now: float) -> None:
        """Record a successful call.

        Resets error count if cooldown has expired.

        Args:
            now: Current timestamp
        """
        if self.cooldown_until is not None and now >= self.cooldown_until:
            if self.error_count > 0:
                logger.info(
                    "Provider %s recovered after %d errors",
                    self.provider_id,
                    self.error_count,
                )
            self.error_count = 0
            self.cooldown_until = None


@dataclass
class FallbackAttempt:
    """Record of a single fallback attempt."""

    provider_id: str
    model: str
    reason: FailoverReason
    error: str
    timestamp: float = field(default_factory=time.time)


class FallbackChatModel(ChatModelBase):
    """Transparent fallback wrapper around ChatModelBase.

    Automatically switches to backup models when the primary model fails
    due to rate limits, timeouts, or service errors. All while preserving
    conversation context and remaining transparent to agent logic.

    The wrapper chain order: TokenRecordingModelWrapper → FallbackChatModel
        → RetryChatModel → Actual Model

    Example:
        >>> config = ModelFallbackConfig(
        ...     fallbacks=[FallbackModelConfig(
        ...         provider_id="anthropic", model="claude"
        ...     )]
        ... )
        >>> fallback_model = FallbackChatModel(
        ...     inner=primary_model,
        ...     fallback_config=config,
        ...     provider_manager=provider_manager,
        ... )
    """

    def __init__(
        self,
        inner: ChatModelBase,
        fallback_config: ModelFallbackConfig,
        provider_manager: "ProviderManager",
        primary_provider_id: Optional[str] = None,
        primary_model: Optional[str] = None,
    ) -> None:
        """Initialize the fallback wrapper.

        Args:
            inner: The primary chat model to wrap
            fallback_config: Fallback configuration with backup models
            provider_manager: ProviderManager instance for creating models
            primary_provider_id: Provider ID of the primary model
            primary_model: Model name of the primary model
        """
        super().__init__(model_name=inner.model_name, stream=inner.stream)
        self._inner = inner
        self._fallback_config = fallback_config
        self._provider_manager = provider_manager

        # Store primary model info explicitly (fixes TODO about tracking)
        self._primary_provider_id = primary_provider_id or getattr(
            inner,
            "_provider_id",
            None,
        )
        self._primary_model = primary_model or getattr(
            inner,
            "model_name",
            None,
        )

        # Cooldown states are now managed by ProviderManager (singleton)
        # to ensure persistence across model instances
        self._attempt_history: List[FallbackAttempt] = []

        # Set provider_id on inner model for consistency
        if primary_provider_id and not hasattr(inner, "_provider_id"):
            inner._provider_id = primary_provider_id

    @property
    def inner_class(self) -> type:
        """Expose the real model's class for formatter mapping."""
        return self._inner.__class__

    def _get_or_create_cooldown_state(
        self,
        provider_id: str,
    ) -> CooldownState:
        """Get or create cooldown state for a provider.

        Uses ProviderManager's singleton storage to ensure
        cooldown states persist across model instances.

        Args:
            provider_id: The provider identifier

        Returns:
            CooldownState instance for the provider
        """
        return self._provider_manager.get_cooldown_state(provider_id)

    def _build_candidate_chain(self) -> List[ModelSlotConfig]:
        """Build the chain of model candidates to try.

        Returns:
            List of ModelSlotConfig in order of preference
        """
        candidates: List[ModelSlotConfig] = []
        seen: set = set()

        # Add primary model (explicitly tracked in __init__)
        if self._primary_provider_id and self._primary_model:
            key = f"{self._primary_provider_id}:{self._primary_model}"
            if key not in seen:
                seen.add(key)
                candidates.append(
                    ModelSlotConfig(
                        provider_id=self._primary_provider_id,
                        model=self._primary_model,
                    ),
                )

        # Add configured fallbacks
        for fallback in self._fallback_config.fallbacks:
            key = f"{fallback.provider_id}:{fallback.model}"
            if key not in seen:
                seen.add(key)
                candidates.append(
                    ModelSlotConfig(
                        provider_id=fallback.provider_id,
                        model=fallback.model,
                    ),
                )

        return candidates

    def _filter_available_candidates(
        self,
        candidates: List[ModelSlotConfig],
        now: float,
    ) -> Tuple[List[ModelSlotConfig], List[ModelSlotConfig]]:
        """Filter candidates into available and cooldown groups.

        Args:
            candidates: All candidate models
            now: Current timestamp

        Returns:
            Tuple of (available_candidates, cooldown_candidates)
        """
        available: List[ModelSlotConfig] = []
        in_cooldown: List[ModelSlotConfig] = []

        for candidate in candidates:
            state = self._get_or_create_cooldown_state(candidate.provider_id)
            if state.is_in_cooldown(now):
                in_cooldown.append(candidate)
            else:
                available.append(candidate)

        return available, in_cooldown

    async def _try_candidate(
        self,
        candidate: ModelSlotConfig,
        args: Tuple,
        kwargs: Dict[str, Any],
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        """Try to execute with a candidate model.

        Args:
            candidate: The model slot configuration to try
            args: Positional arguments for the model call
            kwargs: Keyword arguments for the model call

        Returns:
            Model response or async generator

        Raises:
            Exception: If the candidate fails
        """
        # If this is the primary model (inner), use it directly
        # Otherwise, create a new model instance
        if candidate == self._get_primary_candidate():
            model = self._inner
        else:
            model = self._create_model_for_candidate(candidate)

        logger.debug(
            "Trying candidate: %s/%s",
            candidate.provider_id,
            candidate.model,
        )

        result = await model(*args, **kwargs)

        # Record success to reset cooldown
        state = self._get_or_create_cooldown_state(candidate.provider_id)
        state.record_success(time.time())

        return result

    def _get_primary_candidate(self) -> Optional[ModelSlotConfig]:
        """Get the primary model candidate.

        Returns:
            ModelSlotConfig for the primary model, or None if not tracked
        """
        if self._primary_provider_id and self._primary_model:
            return ModelSlotConfig(
                provider_id=self._primary_provider_id,
                model=self._primary_model,
            )
        return None

    def _create_model_for_candidate(
        self,
        candidate: ModelSlotConfig,
    ) -> ChatModelBase:
        """Create a chat model instance for a candidate.

        Creates a properly wrapped model with TokenRecordingModelWrapper
        and RetryChatModel for fallback candidates.

        Args:
            candidate: Model slot configuration

        Returns:
            ChatModelBase instance (wrapped)
        """
        provider = self._provider_manager.get_provider(candidate.provider_id)
        if provider is None:
            raise ValueError(f"Provider '{candidate.provider_id}' not found")

        if getattr(provider, "is_local", False):
            from ..local_models import create_local_chat_model

            model = create_local_chat_model(
                model_id=candidate.model,
                stream=True,
                generate_kwargs={"max_tokens": None},
            )
        else:
            model = provider.get_chat_model_instance(candidate.model)

        # Wrap with token recording and retry logic
        # Import here to avoid circular imports
        from ..token_usage import TokenRecordingModelWrapper
        from .retry_chat_model import RetryChatModel

        model = TokenRecordingModelWrapper(candidate.provider_id, model)
        model = RetryChatModel(model)

        return model

    async def _wrap_stream_with_fallback(
        self,
        stream: AsyncGenerator[ChatResponse, None],
        candidate: ModelSlotConfig,
        args: Tuple,
        kwargs: Dict[str, Any],
        remaining_candidates: List[ModelSlotConfig],
        attempts: List[Dict[str, Any]],
    ) -> AsyncGenerator[ChatResponse, None]:
        """Wrap a stream to handle mid-stream failures with fallback.

        If the stream fails, this generator will automatically try the next
        candidate and yield from that stream instead.

        Args:
            stream: The current stream
            candidate: The candidate that produced this stream
            args: Original positional arguments
            kwargs: Original keyword arguments
            remaining_candidates: Candidates to try if this stream fails
            attempts: List to record failed attempts

        Yields:
            ChatResponse chunks from the successful stream
        """
        failed_exc: Exception | None = None

        try:
            async for chunk in stream:
                yield chunk
            return  # Stream completed successfully
        except Exception as exc:
            failed_exc = exc
            # Close the failed stream
            await stream.aclose()

        if failed_exc is None:
            return

        # Classify the error
        reason = _classify_error(failed_exc)

        # Non-recoverable errors: rethrow immediately
        if reason in NON_RECOVERABLE_ERRORS:
            logger.warning(
                "Non-recoverable error in stream (%s), "
                "not trying fallbacks: %s",
                reason.value,
                failed_exc,
            )
            raise failed_exc

        # Record the failed attempt
        attempt = FallbackAttempt(
            provider_id=candidate.provider_id,
            model=candidate.model,
            reason=reason,
            error=str(failed_exc),
        )
        self._attempt_history.append(attempt)
        attempts.append(
            {
                "provider": candidate.provider_id,
                "model": candidate.model,
                "reason": reason.value,
                "error": str(failed_exc),
            },
        )

        logger.warning(
            "Stream from %s/%s failed (%s): %s",
            candidate.provider_id,
            candidate.model,
            reason.value,
            failed_exc,
        )

        # Mark provider in cooldown if enabled
        if self._fallback_config.cooldown_enabled:
            state = self._get_or_create_cooldown_state(candidate.provider_id)
            state.record_failure(time.time(), reason)

        # Try remaining candidates
        for _, next_candidate in enumerate(remaining_candidates):
            try:
                logger.info(
                    "Trying fallback model: %s/%s",
                    next_candidate.provider_id,
                    next_candidate.model,
                )

                result = await self._try_candidate(
                    next_candidate,
                    args,
                    kwargs,
                )

                if isinstance(result, AsyncGenerator):
                    # Yield from the fallback stream
                    logger.warning(
                        "Model fallback: %s/%s -> %s/%s (stream)",
                        self._primary_provider_id,
                        self._primary_model,
                        next_candidate.provider_id,
                        next_candidate.model,
                    )
                    async for chunk in result:
                        yield chunk
                    return
                else:
                    # Non-streaming response - yield as single chunk
                    logger.warning(
                        "Model fallback: %s/%s -> %s/%s",
                        self._primary_provider_id,
                        self._primary_model,
                        next_candidate.provider_id,
                        next_candidate.model,
                    )
                    yield result
                    return

            except Exception as exc:
                reason = _classify_error(exc)

                if reason in NON_RECOVERABLE_ERRORS:
                    raise

                attempt = FallbackAttempt(
                    provider_id=next_candidate.provider_id,
                    model=next_candidate.model,
                    reason=reason,
                    error=str(exc),
                )
                self._attempt_history.append(attempt)
                attempts.append(
                    {
                        "provider": next_candidate.provider_id,
                        "model": next_candidate.model,
                        "reason": reason.value,
                        "error": str(exc),
                    },
                )

                if self._fallback_config.cooldown_enabled:
                    state = self._get_or_create_cooldown_state(
                        next_candidate.provider_id,
                    )
                    state.record_failure(time.time(), reason)

                continue

        # All candidates exhausted
        raise FallbackExhaustedError(attempts)

    async def __call__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        """Execute with fallback support (async).

        Tries the primary model first, then falls back through the
        configured fallback chain on transient errors.

        Args:
            *args: Positional arguments for model call
            **kwargs: Keyword arguments for model call

        Returns:
            Model response or async generator

        Raises:
            FallbackExhaustedError: If all candidates fail
            Exception: If a non-recoverable error occurs
        """
        now = time.time()
        candidates = self._build_candidate_chain()

        if not candidates:
            logger.warning(
                "No fallback candidates configured, using primary model",
            )
            return await self._inner(*args, **kwargs)

        # Filter available candidates (respecting cooldown)
        available, in_cooldown = self._filter_available_candidates(
            candidates,
            now,
        )

        # Limit to max_fallbacks + 1 (primary + fallbacks)
        max_candidates = self._fallback_config.max_fallbacks + 1
        # prioritized_candidates: ordered by availability (available first,
        # then cooldown). This ensures we try available providers first, but
        # can still use cooldown providers if all available ones fail.
        prioritized_candidates = (available + in_cooldown)[:max_candidates]

        if not prioritized_candidates:
            logger.error(
                "All providers are in cooldown, trying primary anyway",
            )
            prioritized_candidates = candidates[:1]

        attempts: List[Dict[str, Any]] = []

        for idx, candidate in enumerate(prioritized_candidates):
            # Log if we're trying a fallback (not the primary)
            if idx > 0:
                logger.info(
                    "Trying fallback model: %s/%s",
                    candidate.provider_id,
                    candidate.model,
                )
            try:
                result = await self._try_candidate(candidate, args, kwargs)

                # If result is a stream, wrap it for potential
                # mid-stream fallback
                if isinstance(result, AsyncGenerator):
                    remaining = prioritized_candidates[idx + 1 :]
                    return self._wrap_stream_with_fallback(
                        result,
                        candidate,
                        args,
                        kwargs,
                        remaining,
                        attempts,
                    )

                # Log fallback success if we used a fallback
                if idx > 0:
                    logger.warning(
                        "Model fallback: %s/%s -> %s/%s",
                        self._primary_provider_id,
                        self._primary_model,
                        candidate.provider_id,
                        candidate.model,
                    )

                return result

            except Exception as exc:
                reason = _classify_error(exc)

                # Non-recoverable errors: rethrow immediately
                if reason in NON_RECOVERABLE_ERRORS:
                    logger.warning(
                        "Non-recoverable error (%s), not trying fallbacks: %s",
                        reason.value,
                        exc,
                    )
                    raise

                # Record the attempt
                attempt = FallbackAttempt(
                    provider_id=candidate.provider_id,
                    model=candidate.model,
                    reason=reason,
                    error=str(exc),
                )
                self._attempt_history.append(attempt)
                attempts.append(
                    {
                        "provider": candidate.provider_id,
                        "model": candidate.model,
                        "reason": reason.value,
                        "error": str(exc),
                    },
                )

                logger.warning(
                    "Candidate %s/%s failed (%s): %s",
                    candidate.provider_id,
                    candidate.model,
                    reason.value,
                    exc,
                )

                # Mark provider in cooldown if enabled
                if self._fallback_config.cooldown_enabled:
                    state = self._get_or_create_cooldown_state(
                        candidate.provider_id,
                    )
                    state.record_failure(time.time(), reason)

                # Continue to next fallback
                continue

        # All candidates exhausted
        raise FallbackExhaustedError(attempts)

    def chat(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> ChatResponse:
        """Execute with fallback support (synchronous).

        This is a synchronous wrapper around the async `__call__` method.
        Uses asyncio.run() for proper event loop lifecycle management.
        For streaming responses, use `__call__` directly.

        Args:
            *args: Positional arguments for model call
            **kwargs: Keyword arguments for model call

        Returns:
            Model response (non-streaming)

        Raises:
            FallbackExhaustedError: If all candidates fail
            Exception: If a non-recoverable error occurs
            RuntimeError: If called within an async context

        Example:
            >>> response = model.chat(
            ...     messages=[{"role": "user", "content": "Hello"}]
            ... )
            >>> print(response.text)
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No event loop running, safe to use asyncio.run()
            return asyncio.run(self(*args, **kwargs))
        else:
            # We're in an async context
            raise RuntimeError(
                "Cannot use synchronous chat() within an async context. "
                "Use await model(...) instead.",
            )

    def get_attempt_history(self) -> List[FallbackAttempt]:
        """Get history of fallback attempts.

        Returns:
            List of FallbackAttempt records
        """
        return self._attempt_history.copy()

    def clear_attempt_history(self) -> None:
        """Clear the attempt history."""
        self._attempt_history.clear()

    def get_cooldown_states(self) -> Dict[str, CooldownState]:
        """Get current cooldown states for all providers.

        Returns:
            Dictionary mapping provider_id to CooldownState
        """
        return self._provider_manager.get_all_cooldown_states()
