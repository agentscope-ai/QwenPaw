# -*- coding: utf-8 -*-
"""Request policies shared by session readers and writers."""

from typing import Any

from .agents.acp.meta import ACP_EPHEMERAL_META_KEY


def is_ephemeral_request(request: Any) -> bool:
    """Use the same temporary-request policy before and inside Runtime."""
    context = getattr(request, "request_context", None)
    if not isinstance(context, dict):
        return False
    value = context.get(ACP_EPHEMERAL_META_KEY)
    return value is True or (
        isinstance(value, str) and value.lower() in {"1", "true", "yes"}
    )
