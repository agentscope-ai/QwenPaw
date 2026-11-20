"""Scoped live progress for CloudPaw A2A calls and their browser subscribers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from qwenpaw.pawapp.task import SSEBroadcast
from qwenpaw.plugins.http_scope import runtime_plugin_scope


_streams: dict = {}


def start_stream() -> SSEBroadcast:
    scope = runtime_plugin_scope()
    if scope in _streams:
        raise RuntimeError("An A2A call is already in progress in this workspace")
    stream = SSEBroadcast()
    _streams[scope] = stream
    return stream


def get_stream() -> SSEBroadcast | None:
    return _streams.get(runtime_plugin_scope())


def finish_stream() -> None:
    stream = _streams.pop(runtime_plugin_scope(), None)
    if stream is not None:
        stream.publish({"done": True})
        stream.close()


async def read_stream_sse() -> AsyncIterator[str]:
    stream = get_stream()
    for _ in range(30):
        if stream is not None:
            break
        await asyncio.sleep(0.1)
        stream = get_stream()
    if stream is None:
        msg = json.dumps({"done": True, "error": "no active call"})
        yield f"data: {msg}\n\n"
        return
    async for chunk in stream.stream():
        yield chunk
