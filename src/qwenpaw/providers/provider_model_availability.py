# -*- coding: utf-8 -*-
"""Availability classification for provider model connection checks."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from .error_sanitizer import (
    CONNECTION_MESSAGE_SCAN_LIMIT,
    is_challenge_page,
)
from .error_utils import extract_http_status
from .provider import Provider


class ProviderModelCheckResult(BaseModel):
    """Structured result of checking whether a model is usable."""

    success: bool
    status: Literal[
        "available",
        "blocked",
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


def classify_model_check(
    success: bool,
    message: str,
    *,
    http_status: int | None = None,
    error_kind: str | None = None,
    raw_message: str | None = None,
    verification: Literal[
        "live",
        "provider_only",
        "catalog",
        "unverified",
    ] = "unverified",
) -> ProviderModelCheckResult:
    """Convert provider check output into stable availability states."""
    checked_at = datetime.now(timezone.utc).isoformat()
    # Classify on the uncleaned text: cleanup rewrites a challenge page
    # and summarizes an HTML page from its opening, which would drop
    # both a "status=NNN" prefix and any marker further into the body,
    # and downgrade a non-retryable denial into a retryable error. A
    # caller that already cleaned ``message`` passes the original text
    # as ``raw_message``.
    text = (raw_message or message or "").strip()
    if http_status is None:
        http_status = extract_http_status(text)
    normalized = text[:CONNECTION_MESSAGE_SCAN_LIMIT].lower()
    # Only now that everything above has read the uncleaned text, cap
    # what is reported: the message is persisted with the provider
    # config as ``availability_message`` and returned to the Console.
    message = Provider.truncate_connection_message(
        Provider.sanitize_connection_message(message),
    )

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

    if error_kind == "blocked" or is_challenge_page(text):
        # A challenge answers 403, so it has to be recognized before the
        # permission checks below, which would otherwise blame the
        # credentials and show a "No permission" badge for a bot block.
        # Retrying does not help, so the state is not retryable. Some
        # providers derive "permission_denied" from the 403 themselves,
        # so the page check has to win over that kind as well.
        status = "blocked"
        retryable = False
    elif error_kind in {
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
