# -*- coding: utf-8 -*-
"""Internal SDK ToolChunk bridge; preserves ownership and generator close."""

# Host adapters access private ownership state behind the public SDK.
# pylint: disable=protected-access

from ._workspace import workspace_id


async def sdk_function_call(self, **arguments):
    # Bind the real published tool's request identity, independently of path
    # layout. Reset around each yield so cross-task stream consumers stay safe.
    owner = (getattr(self, "_qp_request_context", None) or {}).get("agent_id")
    owner = owner or getattr(self, "_qp_agent_id", None)
    source = self._func(**arguments)

    async def stream():
        try:
            while True:
                token = workspace_id.set(owner) if owner else None
                try:
                    chunk = await anext(source)
                except StopAsyncIteration:
                    return
                finally:
                    if token is not None:
                        workspace_id.reset(token)
                yield chunk
        finally:
            token = workspace_id.set(owner) if owner else None
            try:
                await source.aclose()
            finally:
                if token is not None:
                    workspace_id.reset(token)

    return stream()
