# -*- coding: utf-8 -*-
"""Internal bridges from trusted host request contexts."""

from contextvars import ContextVar
from typing import TYPE_CHECKING

from .context import RequestContext

if TYPE_CHECKING:
    from .tools import ToolContext

request_identity: ContextVar[RequestContext | None] = ContextVar(
    "sdk_request_identity",
    default=None,
)

control_context: ContextVar[tuple["ToolContext", object] | None] = ContextVar(
    "sdk_control_context",
    default=None,
)


def from_runtime(runtime) -> RequestContext:
    request = getattr(runtime, "request", None)
    # Legacy prompt assembly supplies an Agent rather than HookContext. Both
    # are host-owned; never inspect plugin/client-supplied metadata for identity.
    legacy = getattr(runtime, "_request_context", {}) or {}
    return RequestContext(
        getattr(runtime, "agent_id", "") or legacy.get("agent_id", ""),
        getattr(runtime, "session_id", "") or legacy.get("session_id", ""),
        getattr(request, "channel", "") or legacy.get("channel", ""),
        getattr(request, "user_id", "") or legacy.get("user_id", ""),
    )
