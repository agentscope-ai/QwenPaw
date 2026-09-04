# -*- coding: utf-8 -*-
"""Helpers for interpreting per-request runtime metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..agents.acp.meta import ACP_EPHEMERAL_META_KEY

_TRUTHY_VALUES = {"1", "true", "yes"}


def is_ephemeral_request_context(
    request_context: Mapping[str, Any] | None,
) -> bool:
    """Return whether request metadata opts out of resumable state."""
    if not isinstance(request_context, Mapping):
        return False
    value = request_context.get(ACP_EPHEMERAL_META_KEY)
    if value is True:
        return True
    return isinstance(value, str) and value.lower() in _TRUTHY_VALUES


def is_ephemeral_request(ctx: Any) -> bool:
    """Return whether a runtime context opts out of resumable state."""
    request = getattr(ctx, "request", None)
    request_context = getattr(request, "request_context", None)
    return is_ephemeral_request_context(request_context)


__all__ = ["is_ephemeral_request", "is_ephemeral_request_context"]
