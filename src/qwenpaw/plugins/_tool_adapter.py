# -*- coding: utf-8 -*-
"""Internal SDK ToolChunk bridge; preserves ownership and generator close."""

# Host adapters access private ownership state behind the public SDK.
# pylint: disable=protected-access

from ._workspace import workspace_id
from ._identity import request_identity
from .context import RequestContext


async def sdk_function_call(self, **arguments):
    # Bind the real published tool's request identity, independently of path
    # layout. Reset around each yield so cross-task stream consumers stay safe.
    request = dict(getattr(self, "_qp_request_context", None) or {})
    owner = request.get("agent_id")
    owner = owner or getattr(self, "_qp_agent_id", None)
    identity = RequestContext(
        owner or "",
        request.get("session_id", ""),
        request.get("channel", ""),
        request.get("user_id", ""),
    )
    source = self._func(**arguments)

    async def stream():
        try:
            while True:
                token = workspace_id.set(owner) if owner else None
                identity_token = request_identity.set(identity)
                try:
                    chunk = await anext(source)
                except StopAsyncIteration:
                    return
                finally:
                    request_identity.reset(identity_token)
                    if token is not None:
                        workspace_id.reset(token)
                yield chunk
        finally:
            token = workspace_id.set(owner) if owner else None
            identity_token = request_identity.set(identity)
            try:
                await source.aclose()
            finally:
                request_identity.reset(identity_token)
                if token is not None:
                    workspace_id.reset(token)

    return stream()
