# -*- coding: utf-8 -*-
"""Fallback wrapper for ordered chat model candidates."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse

from .retry_chat_model import (
    _safe_error_summary,
    is_retryable_llm_error,
)

FALLBACK_ONLY_STATUS_CODES = {401, 403, 404}

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FallbackCandidate:
    """One fully wrapped model candidate."""

    provider_id: str
    model_name: str
    model: ChatModelBase

    @property
    def label(self) -> str:
        """Return a short provider:model identifier for logging."""
        return f"{self.provider_id}:{self.model_name}"


class ModelFallbackError(Exception):
    """Raised when every fallback candidate fails."""

    def __init__(self, failures: list[tuple[FallbackCandidate, Exception]]):
        self.failures = failures
        detail = "; ".join(
            f"{candidate.label} -> {_safe_error_summary(exc)}"
            for candidate, exc in failures
        )
        super().__init__(f"All fallback model candidates failed: {detail}")


def is_fallback_eligible_error(exc: Exception) -> bool:
    """Return True when *exc* is safe to handle via model fallback."""

    if is_retryable_llm_error(exc):
        return True
    status = getattr(exc, "status_code", None)
    return status in FALLBACK_ONLY_STATUS_CODES


class FallbackChatModel(ChatModelBase):
    """Try ordered model candidates after retryable candidate failures."""

    # ChatModelBase subclasses expose behavior primarily via __call__.
    # pylint: disable=too-few-public-methods

    def __init__(self, candidates: list[FallbackCandidate]) -> None:
        """Initialize with the ordered list of fallback candidates."""
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

    async def __call__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        failures: list[tuple[FallbackCandidate, Exception]] = []

        for index, candidate in enumerate(self.candidates):
            try:
                result = await candidate.model(*args, **kwargs)
            except Exception as exc:  # pylint: disable=broad-except
                failures.append((candidate, exc))
                if not is_fallback_eligible_error(exc):
                    raise
                if index >= len(self.candidates) - 1:
                    raise ModelFallbackError(failures) from exc
                self._log_fallback(candidate, exc, index)
                continue

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

    def _should_try_next(self, exc: Exception, index: int) -> bool:
        return (
            is_fallback_eligible_error(exc)
            and index < len(self.candidates) - 1
        )

    @staticmethod
    def _log_fallback(
        candidate: FallbackCandidate,
        exc: Exception,
        index: int,
    ) -> None:
        logger.warning(
            "LLM fallback candidate failed: index=%d provider=%s model=%s "
            "error=%s",
            index,
            candidate.provider_id,
            candidate.model_name,
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
            "LLM fallback candidate selected: index=%d provider=%s "
            "model=%s previous_failures=%d",
            index,
            candidate.provider_id,
            candidate.model_name,
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
        # Stream restart needs explicit context; keyword-only keeps call sites
        # readable. pylint: disable=too-many-arguments
        yielded_any = False
        try:
            async for chunk in stream:
                yielded_any = True
                yield chunk
            return
        except Exception as exc:  # pylint: disable=broad-except
            if yielded_any:
                raise
            failures.append((candidate, exc))
            if not is_fallback_eligible_error(exc):
                raise
            if candidate_index >= len(self.candidates) - 1:
                raise ModelFallbackError(failures) from exc
            self._log_fallback(candidate, exc, candidate_index)

        for index in range(candidate_index + 1, len(self.candidates)):
            next_candidate = self.candidates[index]
            yielded_any = False
            try:
                result = await next_candidate.model(*call_args, **call_kwargs)
                self._log_selected(next_candidate, index, failures)
                if isinstance(result, AsyncGenerator):
                    async for chunk in result:
                        yielded_any = True
                        yield chunk
                    return
                yield result
                return
            except Exception as exc:  # pylint: disable=broad-except
                if yielded_any:
                    raise
                failures.append((next_candidate, exc))
                if not is_fallback_eligible_error(exc):
                    raise
                if index >= len(self.candidates) - 1:
                    raise ModelFallbackError(failures) from exc
                self._log_fallback(next_candidate, exc, index)

        raise ModelFallbackError(failures)
