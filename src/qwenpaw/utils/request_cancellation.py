# -*- coding: utf-8 -*-
"""Cancellation for HTTP handlers whose request body is already consumed."""

import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from starlette.requests import Request


class ClientDisconnected(Exception):
    """The request's callback has unwound after its client disconnected."""


@asynccontextmanager
async def cancel_on_disconnect(request: Request) -> AsyncIterator[None]:
    # ASGI does not cancel ordinary handlers when the client leaves. Cancel
    # the owner, so callback finally blocks finish before the route returns.
    owner = asyncio.current_task()
    assert owner is not None
    cancelled_here = False

    async def watch() -> None:
        nonlocal cancelled_here
        while True:
            message = await request.receive()
            if message["type"] == "http.disconnect":
                if not owner.cancelling():
                    cancelled_here = True
                    owner.cancel()
                return

    watcher = asyncio.create_task(watch(), name="http-disconnect")
    try:
        yield
    except asyncio.CancelledError:
        if not cancelled_here or owner.cancelling() > 1:
            raise
        owner.uncancel()
        raise ClientDisconnected from None
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
