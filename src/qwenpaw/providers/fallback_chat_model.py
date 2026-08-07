# -*- coding: utf-8 -*-
"""Fallback wrapper for ordered chat model candidates.

When the primary model exhausts its retries on a transient or permission
failure, the agent can automatically switch to a configured list of backup
models in order.

Design:
- ``FallbackChatModel`` wraps a list of ``FallbackCandidate`` instances.
- The first candidate is the primary model (already wrapped in
  ``RetryChatModel``).  Subsequent candidates are fallback models tried
  in order when the primary fails.
- Non-eligible errors (context overflow, user abort, etc.) are re-raised
  immediately without triggering fallback.
- Cooldown tracking prevents repeatedly hitting a failing provider.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse

from qwenpaw.providers.error_utils import (
    extract_status_code as _extract_status,
)
from qwenpaw.providers.retry_chat_model import (
    is_retryable_llm_error as _is_retryable_llm_error,
)

logger = logging.getLogger(__name__)

__all__ = [
    "FallbackCandidate",
    "FallbackChatModel",
    "CooldownManager",
    "ModelFallbackError",
    "is_fallback_eligible_error",
    "is_retryable_llm_error",
]

# ---- Error classification ---------------------------------------------------

# HTTP status codes that are safe to fallback on (in addition to retryable
# status codes from the retry module).
FALLBACK_ONLY_STATUS_CODES = frozenset({401, 403, 404})

# Cooldown durations (seconds) for transient errors.
TRANSIENT_COOLDOWN_BUCKETS = (60, 300, 1500, 3600)  # 1m → 5m → 25m → 60m
# Cooldown durations for auth/billing errors (longer).
AUTH_COOLDOWN_BUCKETS = (18000, 36000, 72000, 86400)  # 5h → 10h → 20h → 24h


# ---- Data classes -----------------------------------------------------------


@dataclass
class CooldownState:
    """Tracks when a provider:model pair becomes available again."""

    expires_at: float  # unix timestamp
    consecutive_failures: int = 0


@dataclass
class FallbackCandidate:
    """One fully wrapped model candidate."""

    provider_id: str
    model_name: str
    model: ChatModelBase

    @property
    def label(self) -> str:
        return f"{self.provider_id}:{self.model_name}"


# ---- Exceptions -------------------------------------------------------------


class ModelFallbackError(Exception):
    """Raised when every fallback candidate fails."""

    def __init__(self, failures: list[tuple[FallbackCandidate, Exception]]):
        self.failures = failures
        detail = "; ".join(
            f"{c.label} -> {_safe_error_summary(exc)}" for c, exc in failures
        )
        super().__init__(f"All fallback model candidates failed: {detail}")


# ---- Helpers ----------------------------------------------------------------


def _safe_error_summary(exc: Exception) -> str:
    """Return a short human-readable summary of *exc*."""
    status = _extract_status(exc)
    if status is not None:
        return f"HTTP {status}: {exc!s}"[:120]
    return exc.__class__.__name__[:120]


def _extract_status_code(exc: Exception) -> int | None:
    """Try to extract an HTTP status code from *exc*.

    Delegates to the shared ``error_utils.extract_status_code``.
    """
    return _extract_status(exc)


def is_retryable_llm_error(exc: Exception) -> bool:
    """Return *True* if *exc* is a transient error safe to retry/fallback.

    Matches the same logic used by ``RetryChatModel``.
    """
    return _is_retryable_llm_error(exc)


def is_fallback_eligible_error(exc: Exception) -> bool:
    """Return *True* when *exc* is safe to handle via model fallback.

    Fallback-eligible errors include:
    - Retryable errors (rate limits, timeouts, 5xx)
    - Auth/permission errors (401, 403, 404)
    """
    if is_retryable_llm_error(exc):
        return True
    status = _extract_status_code(exc)
    if status is not None and status in FALLBACK_ONLY_STATUS_CODES:
        return True
    return False


def _is_auth_or_billing_error(exc: Exception) -> bool:
    """Return *True* if *exc* is an auth or billing error."""
    status = _extract_status_code(exc)
    return status in (401, 403, 402, 429)


def _compute_cooldown_seconds(
    consecutive_failures: int,
    is_auth: bool,
) -> float:
    """Return the cooldown duration for *consecutive_failures*."""
    buckets = AUTH_COOLDOWN_BUCKETS if is_auth else TRANSIENT_COOLDOWN_BUCKETS
    idx = min(consecutive_failures, len(buckets) - 1)
    return buckets[idx]


# ---- Cooldown manager -------------------------------------------------------


class CooldownManager:
    """Manages per-provider cooldown states.

    Cooldown states are stored in a singleton so they persist across
    model instances and requests.

    Thread-safety: This class is designed for use within a single async
    event loop (no ``await`` between read and write). If QwenPaw ever
    introduces thread-pool concurrency, add an ``asyncio.Lock`` around
    ``_states`` access.
    """

    _states: dict[str, CooldownState] = {}

    @classmethod
    def is_on_cooldown(cls, key: str) -> bool:
        """Return *True* if *key* is on cooldown."""
        state = cls._states.get(key)
        if state is None:
            return False
        if time.time() >= state.expires_at:
            cls._states.pop(key, None)
            return False
        return True

    @classmethod
    def record_failure(cls, key: str, exc: Exception) -> None:
        """Record a failure for *key* and update its cooldown."""
        state = cls._states.get(key)
        if state is None:
            state = CooldownState(expires_at=0, consecutive_failures=0)
            cls._states[key] = state

        state.consecutive_failures += 1
        is_auth = _is_auth_or_billing_error(exc)
        cooldown = _compute_cooldown_seconds(
            state.consecutive_failures,
            is_auth,
        )
        state.expires_at = time.time() + cooldown

    @classmethod
    def record_success(cls, key: str) -> None:
        """Reset cooldown for *key* on success."""
        cls._states.pop(key, None)

    @classmethod
    def get_cooldown_remaining(cls, key: str) -> float:
        """Return remaining cooldown seconds for *key* (0 if none)."""
        state = cls._states.get(key)
        if state is None:
            return 0.0
        remaining = state.expires_at - time.time()
        return max(0.0, remaining)


# ---- FallbackChatModel ------------------------------------------------------


class FallbackChatModel(ChatModelBase):
    """Try ordered model candidates after retryable candidate failures.

    The first candidate is the primary model (already wrapped in
    ``RetryChatModel``).  Subsequent candidates are fallback models
    tried in order when the primary fails.

    Cooldown tracking:
    - When a candidate fails, the provider:model pair enters cooldown.
    - Subsequent requests skip candidates that are on cooldown.
    - Cooldown duration increases with consecutive failures.
    """

    def __init__(self, candidates: list[FallbackCandidate]) -> None:
        if not candidates:
            raise ValueError(
                "FallbackChatModel requires at least one candidate",
            )
        primary = candidates[0]
        super().__init__(
            credential=getattr(primary.model, "credential", None),
            model=getattr(primary.model, "model", primary.model_name),
            parameters=getattr(primary.model, "parameters", None),
            stream=bool(getattr(primary.model, "stream", True)),
            max_retries=getattr(primary.model, "max_retries", 0),
            retry_delay=getattr(primary.model, "retry_delay", 0.0),
            context_size=getattr(primary.model, "context_size", 32768),
        )
        self.candidates = candidates

    @property
    def inner_class(self) -> type:
        """Expose the primary model's class for formatter mapping."""
        return self.candidates[0].model.__class__

    # ---- Public API ---------------------------------------------------------

    async def __call__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        failures: list[tuple[FallbackCandidate, Exception]] = []

        for index, candidate in enumerate(self._active_candidates()):
            try:
                result = await candidate.model(*args, **kwargs)
            except Exception as exc:
                failures.append((candidate, exc))
                self._record_failure(candidate, exc)
                if not is_fallback_eligible_error(exc):
                    raise
                if index >= len(self.candidates) - 1:
                    raise ModelFallbackError(failures) from exc
                self._log_fallback(candidate, exc, index)
                continue

            self._record_success(candidate)
            self._log_selected(candidate, index, failures)
            if isinstance(result, AsyncGenerator):
                return self._wrap_stream_candidate(
                    candidate=candidate,
                    stream=result,
                    failures=failures,
                    candidate_index=index,
                    call_args=args,
                    call_kwargs=kwargs,
                )
            return result

        raise ModelFallbackError(failures)

    # ---- Internal helpers ---------------------------------------------------

    def _active_candidates(self) -> list[FallbackCandidate]:
        """Return candidates that are not on cooldown."""
        active = []
        for c in self.candidates:
            key = c.label
            if CooldownManager.is_on_cooldown(key):
                remaining = CooldownManager.get_cooldown_remaining(key)
                logger.debug(
                    "Skipping candidate %s (on cooldown, %.0fs remaining)",
                    key,
                    remaining,
                )
                continue
            active.append(c)
        if not active:
            # If all candidates are on cooldown, try the primary anyway.
            logger.warning(
                "All fallback candidates on cooldown; trying primary %s",
                self.candidates[0].label,
            )
            active = [self.candidates[0]]
        return active

    @staticmethod
    def _record_failure(candidate: FallbackCandidate, exc: Exception) -> None:
        CooldownManager.record_failure(candidate.label, exc)

    @staticmethod
    def _record_success(candidate: FallbackCandidate) -> None:
        CooldownManager.record_success(candidate.label)

    @staticmethod
    def _log_fallback(
        candidate: FallbackCandidate,
        exc: Exception,
        index: int,
    ) -> None:
        logger.warning(
            "LLM fallback: candidate %d %s failed: %s",
            index,
            candidate.label,
            _safe_error_summary(exc),
        )

    @staticmethod
    def _log_selected(
        candidate: FallbackCandidate,
        index: int,
        failures: list[tuple[FallbackCandidate, Exception]],
    ) -> None:
        if not failures:
            return
        logger.info(
            "LLM fallback: switched to candidate %d %s "
            "(previous failures: %d)",
            index,
            candidate.label,
            len(failures),
        )

    async def _wrap_stream_candidate(
        self,
        *,
        candidate: FallbackCandidate,
        stream: AsyncGenerator[ChatResponse, None],
        failures: list[tuple[FallbackCandidate, Exception]],
        candidate_index: int,
        call_args: tuple[Any, ...],
        call_kwargs: dict[str, Any],
    ) -> AsyncGenerator[ChatResponse, None]:
        """Wrap a streaming candidate to allow fallback before first chunk."""
        yielded_any = False
        try:
            async for chunk in stream:
                yielded_any = True
                yield chunk
            return
        except Exception as exc:
            if yielded_any:
                raise
            self._record_failure(candidate, exc)
            failures.append((candidate, exc))
            if not is_fallback_eligible_error(exc):
                raise
            if candidate_index >= len(self.candidates) - 1:
                raise ModelFallbackError(failures) from exc
            self._log_fallback(candidate, exc, candidate_index)

        # Try remaining candidates
        for index in range(candidate_index + 1, len(self.candidates)):
            next_candidate = self.candidates[index]
            yielded_any = False
            try:
                result = await next_candidate.model(*call_args, **call_kwargs)
                if isinstance(result, AsyncGenerator):
                    async for chunk in result:
                        yielded_any = True
                        yield chunk
                    self._record_success(next_candidate)
                    return
                self._record_success(next_candidate)
                yield result
                return
            except Exception as exc:
                if yielded_any:
                    raise
                self._record_failure(next_candidate, exc)
                failures.append((next_candidate, exc))
                if not is_fallback_eligible_error(exc):
                    raise
                if index >= len(self.candidates) - 1:
                    raise ModelFallbackError(failures) from exc
                self._log_fallback(next_candidate, exc, index)

        raise ModelFallbackError(failures)
