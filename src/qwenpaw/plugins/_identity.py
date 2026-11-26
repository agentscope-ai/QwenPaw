# -*- coding: utf-8 -*-
"""Internal bridges from trusted host request contexts."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from ..runtime.turn_context import current_request_runtime
from .context import RequestContext

if TYPE_CHECKING:
    from ..runtime.hooks import HookContext
    from .tools import ToolContext

request_identity: ContextVar[RequestContext | None] = ContextVar(
    "sdk_request_identity",
    default=None,
)

control_context: ContextVar[tuple["ToolContext", object] | None] = ContextVar(
    "sdk_control_context",
    default=None,
)


@contextmanager
def bind_request_runtime(runtime: "HookContext"):
    """Expose the executing workspace only inside its request."""
    token = current_request_runtime.set(runtime)
    try:
        yield
    finally:
        current_request_runtime.reset(token)


def bound_runtime(identity: RequestContext) -> "HookContext | None":
    """Return the live turn for an exact conversation identity."""
    runtime = current_request_runtime.get()
    if (
        runtime is not None
        and identity.session_id
        and identity.user_id
        and getattr(runtime.workspace, "agent_id", None)
        == identity.workspace_id
        and identity == from_runtime(runtime)
    ):
        return runtime
    return None


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
