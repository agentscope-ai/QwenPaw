# -*- coding: utf-8 -*-
"""Shared transient-failure classification for media execution services.

Transient provider failures may be retried on a derived durable slot;
deterministic rejections (safety refusals, validation errors) never are.
Markers are matched case-insensitively against the persisted task error.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

TRANSIENT_ERROR_MARKERS = (
    "connection",
    "timeout",
    "timed out",
    "temporarily unavailable",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "too many requests",
    # EBADF from a torn-down socket during download: the transport failed,
    # not the request — field runs showed httpx surfacing it mid-transfer.
    "bad file descriptor",
    "status 429",
    "status 502",
    "status 503",
    "status 504",
)

MAX_TRANSIENT_RETRY_SLOTS = 3


def is_transient_error_message(message: str) -> bool:
    folded = message.casefold()
    return any(marker in folded for marker in TRANSIENT_ERROR_MARKERS)


def is_transient_task_error(error: Mapping[str, Any] | None) -> bool:
    if not isinstance(error, Mapping):
        return False
    if error.get("retryable") is True:
        return True
    return is_transient_error_message(str(error.get("message") or ""))


def transient_retry_slot_key(idempotency_key: str, attempt: int) -> str:
    if attempt == 0:
        return idempotency_key
    # ":" keeps the derived key a safe runtime path segment, because r2v
    # persists the slot key as Task idempotency_key / caused_by_request_id.
    return f"{idempotency_key}:transient-retry-{attempt}"


__all__ = [
    "MAX_TRANSIENT_RETRY_SLOTS",
    "TRANSIENT_ERROR_MARKERS",
    "is_transient_error_message",
    "is_transient_task_error",
    "transient_retry_slot_key",
]
