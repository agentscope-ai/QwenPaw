# -*- coding: utf-8 -*-
"""Availability classification for provider model connection checks."""

import re
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from .provider import Provider


class ProviderModelCheckResult(BaseModel):
    """Structured result of checking whether a model is usable."""

    success: bool
    status: Literal[
        "available",
        "permission_denied",
        "model_not_found",
        "incompatible_api",
        "rate_limited",
        "transient_error",
        "unverified",
    ]
    message: str = ""
    http_status: int | None = None
    retryable: bool = True
    checked_at: str
    verification: Literal[
        "live",
        "provider_only",
        "catalog",
        "unverified",
    ] = "unverified"


def extract_http_status(message: str) -> int | None:
    """Extract an HTTP status code from provider error text."""
    patterns = (
        r"\bstatus\s*[=:]\s*(\d{3})\b",
        r"\bstatus[_ ]code\s*[=:]\s*(\d{3})\b",
        r"\berror\s+code\s*:\s*(\d{3})\b",
        r"\bhttp\s+(\d{3})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def classify_model_check(
    success: bool,
    message: str,
    *,
    http_status: int | None = None,
    error_kind: str | None = None,
    verification: Literal[
        "live",
        "provider_only",
        "catalog",
        "unverified",
    ] = "unverified",
) -> ProviderModelCheckResult:
    """Convert provider check output into stable availability states."""
    checked_at = datetime.now(timezone.utc).isoformat()
    message = Provider.sanitize_connection_message((message or "").strip())
    if http_status is None:
        http_status = extract_http_status(message)
    normalized = message.lower()

    if success:
        return ProviderModelCheckResult(
            success=True,
            status="available",
            message=message,
            http_status=http_status,
            retryable=False,
            checked_at=checked_at,
            verification=verification,
        )

    permission_markers = (
        "unauthorized",
        "forbidden",
        "permission denied",
        "permission_denied",
        "access denied",
        "invalid api key",
        "incorrect api key",
        "authentication",
        "not activated",
        "not enabled",
        "\u65e0\u6743\u9650",
        "\u672a\u5f00\u901a",
    )
    not_found_markers = (
        "model not found",
        "model_not_found",
        "unknown model",
        "does not exist",
        "no such model",
        "\u6a21\u578b\u4e0d\u5b58\u5728",
        "\u6a21\u578b\u5df2\u4e0b\u7ebf",
    )
    incompatible_markers = (
        "unsupported model",
        "does not support chat",
        "not support chat",
        "chat completions is not supported",
        "chat completion is not supported",
        "incompatible api",
        "incompatible endpoint",
        "unsupported endpoint",
        "\u4e0d\u652f\u6301\u5bf9\u8bdd",
        "\u4e0d\u652f\u6301chat",
    )

    if error_kind in {
        "permission_denied",
        "model_not_found",
        "incompatible_api",
    }:
        status = error_kind
        retryable = False
    elif http_status in (401, 403) or any(
        marker in normalized for marker in permission_markers
    ):
        status = "permission_denied"
        retryable = False
    elif any(marker in normalized for marker in not_found_markers):
        status = "model_not_found"
        retryable = False
    elif any(marker in normalized for marker in incompatible_markers):
        status = "incompatible_api"
        retryable = False
    elif http_status == 404:
        status = "model_not_found"
        retryable = False
    elif http_status == 429 or "rate limit" in normalized:
        status = "rate_limited"
        retryable = True
    else:
        status = "transient_error"
        retryable = True

    return ProviderModelCheckResult(
        success=False,
        status=status,
        message=message,
        http_status=http_status,
        retryable=retryable,
        checked_at=checked_at,
        verification=verification,
    )
