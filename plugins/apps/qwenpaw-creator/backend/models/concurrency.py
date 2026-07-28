# -*- coding: utf-8 -*-
"""Shared async concurrency limits for model calls."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from models import config

_limiters: dict[str, tuple[int, asyncio.Semaphore]] = {}


def _get_limiter(name: str, limit: int) -> asyncio.Semaphore:
    current_limit, limiter = _limiters.get(name, (0, None))
    if limiter is None or current_limit != limit:
        limiter = asyncio.Semaphore(limit)
        _limiters[name] = (limit, limiter)
    return limiter


@asynccontextmanager
async def model_slot(kind: str) -> AsyncIterator[None]:
    """Acquire the configured concurrency slot for a model kind."""
    if kind == "text":
        limit = config.TEXT_CONCURRENCY
    elif kind == "image":
        limit = config.get_image_concurrency()
    elif kind == "video":
        limit = config.VIDEO_CONCURRENCY
    elif kind == "vlm":
        limit = config.get_vlm_concurrency()
    else:
        raise ValueError(f"Unknown model concurrency kind: {kind}")

    limiter = _get_limiter(kind, limit)
    async with limiter:
        yield
