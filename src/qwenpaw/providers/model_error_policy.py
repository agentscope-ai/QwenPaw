# -*- coding: utf-8 -*-
"""Shared error classification for retries, checks, and model fallback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import anthropic
import httpx
import openai

from .error_utils import extract_status_code

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504, 529})

ModelErrorKind = Literal[
    "authentication",
    "bad_request",
    "context_overflow",
    "content_safety",
    "model_not_found",
    "rate_limited",
    "transient",
    "unknown",
]

_SDK_RATE_LIMIT_ERRORS = (
    openai.RateLimitError,
    anthropic.RateLimitError,
)
_SDK_TRANSIENT_ERRORS = (
    httpx.NetworkError,
    httpx.TimeoutException,
    httpx.RemoteProtocolError,
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.InternalServerError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.InternalServerError,
)


def _is_sdk_rate_limit(exc: Exception) -> bool:
    """Return whether an installed SDK identifies a rate-limit error."""
    return isinstance(exc, _SDK_RATE_LIMIT_ERRORS)


def _is_sdk_transient(exc: Exception) -> bool:
    """Return whether an installed SDK identifies a transient failure."""
    return isinstance(exc, _SDK_TRANSIENT_ERRORS)


@dataclass(frozen=True, slots=True)
class ModelErrorDecision:
    """Stable model error policy result."""

    kind: ModelErrorKind
    status_code: int | None
    retryable: bool
    fallback_eligible: bool


def classify_model_error(exc: Exception) -> ModelErrorDecision:
    """Classify whether a model error may retry or cross-model fallback."""
    status = extract_status_code(exc)
    message = str(exc).lower()
    if status in {401, 403}:
        kind: ModelErrorKind = "authentication"
    elif status == 404 or "model not found" in message:
        kind = "model_not_found"
    elif status == 429 or _is_sdk_rate_limit(exc):
        kind = "rate_limited"
    elif (
        status in RETRYABLE_STATUS_CODES
        or isinstance(
            exc,
            (ConnectionError, TimeoutError),
        )
        or _is_sdk_transient(exc)
    ):
        kind = "transient"
    elif any(
        marker in message
        for marker in (
            "context length",
            "context_length",
            "maximum context",
            "too many tokens",
        )
    ):
        kind = "context_overflow"
    elif any(
        marker in message
        for marker in (
            "content policy",
            "content_policy",
            "content safety",
            "safety_filter",
            "moderation",
        )
    ):
        kind = "content_safety"
    elif status is not None and 400 <= status < 500:
        kind = "bad_request"
    else:
        kind = "unknown"
    retryable = kind in {"rate_limited", "transient"}
    fallback_eligible = retryable or kind == "model_not_found"
    return ModelErrorDecision(
        kind=kind,
        status_code=status,
        retryable=retryable,
        fallback_eligible=fallback_eligible,
    )


def is_retryable_same_model(exc: Exception) -> bool:
    """Return whether the same model may be retried."""
    return classify_model_error(exc).retryable


def is_fallback_eligible(exc: Exception) -> bool:
    """Return whether the next configured model may be attempted."""
    return classify_model_error(exc).fallback_eligible
