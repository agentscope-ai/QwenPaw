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
    # DNS resolution failures happen before any billable request leaves
    # the machine, so a bounded retry is free. A permanently wrong
    # base_url still surfaces: retry slots exhaust and the terminal
    # message tells the user to check the configuration. Field runs
    # (2026-08-07) showed one [Errno 8] blip locking three nodes.
    "nodename nor servname",  # macOS getaddrinfo EAI_NONAME
    "name or service not known",  # glibc getaddrinfo EAI_NONAME
    "temporary failure in name resolution",  # glibc EAI_AGAIN
    "getaddrinfo",
    "status 429",
    "status 502",
    "status 503",
    "status 504",
    # Legacy empty-detail records: before the provider labelled
    # httpx transport errors, WriteError/ReadError/ConnectError
    # stringified to nothing and persisted this exact degenerate
    # message. Only an empty ``str(exc)`` can produce it, so matching
    # it retroactively reopens nodes walled by a plain network blip
    # (field run 2026-08-10). Real config errors carry a detail and
    # never match.
    "image generation failed: . check",
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
