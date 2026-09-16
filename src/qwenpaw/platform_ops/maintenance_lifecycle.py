"""Hold maintenance admission throughout background operation lifetimes."""

import asyncio
from contextlib import AsyncExitStack, aclosing
from functools import wraps

from .maintenance import MaintenanceBusy, operation


def admitted(function):
    """Acquire in the executing task, including independently scheduled tasks."""

    @wraps(function)
    async def wrapped(*args, **kwargs):
        async with operation():
            return await function(*args, **kwargs)

    return wrapped


def admitted_stream(function):
    """Release only after the producer and its finalizers have closed."""

    @wraps(function)
    async def wrapped(*args, **kwargs):
        async with operation():
            async with aclosing(function(*args, **kwargs)) as stream:
                async for event in stream:
                    yield event

    return wrapped


def admitted_listener(function):
    """Pause an inbound message until admitted; never replay its side effects."""

    @wraps(function)
    async def wrapped(*args, **kwargs):
        async with AsyncExitStack() as stack:
            while True:
                try:
                    await stack.enter_async_context(operation())
                    break
                except MaintenanceBusy:
                    await asyncio.sleep(0.1)
            return await function(*args, **kwargs)

    return wrapped
