# -*- coding: utf-8 -*-
"""Shared error classification for retries, checks, and model fallback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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


def _is_sdk_network_error(exc: Exception) -> bool:
    """Return whether an installed SDK identifies a network failure."""
    network_errors: tuple[type[Exception], ...] = ()
    try:
        import httpx

        network_errors += (httpx.NetworkError, httpx.TimeoutException)
    except ImportError:
        pass
    try:
        import openai

        network_errors += (
            openai.APIConnectionError,
            openai.APITimeoutError,
        )
    except ImportError:
        pass
    try:
        import anthropic

        network_errors += (
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
        )
    except ImportError:
        pass
    return bool(network_errors) and isinstance(exc, network_errors)


@dataclass(frozen=True, slots=True)
class ModelErrorDecision:
    """Stable model error policy result."""

    kind: ModelErrorKind
    status_code: int | None
    retryable: bool
    fallback_eligible: bool


def extract_status_code(exc: Exception) -> int | None:
    """Extract a best-effort HTTP status from common SDK exceptions."""
    status = getattr(exc, "status_code", None)
    if status is not None:
        try:
            return int(status)
        except (TypeError, ValueError):
            pass
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return None
    for container in (body, body.get("error")):
        if not isinstance(container, dict):
            continue
        raw = container.get("status_code", container.get("code"))
        if raw is None:
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def classify_model_error(exc: Exception) -> ModelErrorDecision:
    """Classify whether a model error may retry or cross-model fallback."""
    status = extract_status_code(exc)
    message = str(exc).lower()
    if status in {401, 403}:
        kind: ModelErrorKind = "authentication"
    elif status == 404 or "model not found" in message:
        kind = "model_not_found"
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
    elif status == 429:
        kind = "rate_limited"
    elif (
        status in RETRYABLE_STATUS_CODES
        or isinstance(
            exc,
            (ConnectionError, TimeoutError),
        )
        or _is_sdk_network_error(exc)
    ):
        kind = "transient"
    elif status is not None and 400 <= status < 500:
        kind = "bad_request"
    else:
        kind = "unknown"
    retryable = kind in {"rate_limited", "transient"}
    return ModelErrorDecision(
        kind=kind,
        status_code=status,
        retryable=retryable,
        fallback_eligible=retryable,
    )


def is_retryable_same_model(exc: Exception) -> bool:
    """Return whether the same model may be retried."""
    return classify_model_error(exc).retryable


def is_fallback_eligible(exc: Exception) -> bool:
    """Return whether the next configured model may be attempted."""
    return classify_model_error(exc).fallback_eligible
