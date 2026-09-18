# -*- coding: utf-8 -*-
"""Normalize provider cache counters without double-counting input."""

from contextvars import ContextVar
from typing import Any

CACHE_RESPONSE_HEADERS: ContextVar[dict] = ContextVar(
    f"model_cache_response_headers",
    default={},
)


async def capture_cache_headers(response) -> None:
    """Retain only cache diagnostics in the current request task."""
    status = response.headers.get(f"x-ds-cache-status")
    CACHE_RESPONSE_HEADERS.set(
        {f"x-ds-cache-status": status} if status else {},
    )


def value(record: Any, name: str, default=None):
    """Read SDK records and wire dictionaries with one contract."""
    return (
        record.get(name, default)
        if isinstance(record, dict)
        else getattr(
            record,
            name,
            default,
        )
    )


def cache_usage(usage: Any, raw: Any, headers: Any = None) -> None:
    """Keep raw counters authoritative; headers are diagnostic only."""
    if usage is None or raw is None:
        return
    details = value(raw, f"prompt_tokens_details") or value(
        raw,
        f"input_tokens_details",
    )
    read = value(raw, f"prompt_cache_hit_tokens")
    if read is None:
        read = value(details, f"cached_tokens")
    write = value(details, f"cache_write_tokens")
    if write is None:
        write = value(raw, f"cache_write_tokens")
    for name, count in (
        (f"cache_input_tokens", read),
        (f"cache_creation_input_tokens", write),
    ):
        if type(count) is int and count >= 0:
            setattr(usage, name, count)
    status = headers.get(f"x-ds-cache-status") if headers else None
    if status:
        usage.metadata = {
            **(usage.metadata or {}),
            f"provider_cache_status": str(status),
        }


class UsageStream:
    """Capture raw usage before AgentScope parses the stream."""

    def __init__(self, stream):
        self.stream = stream
        self.active = None
        self.usage = None
        self.headers = getattr(
            getattr(stream, f"response", None), f"headers", {}
        )

    async def __aenter__(self):
        self.active = await self.stream.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.stream.__aexit__(*args)

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.active.__anext__()
        response = value(item, f"response") or item
        usage = value(response, f"usage")
        if usage is not None:
            self.usage = usage
        return item
