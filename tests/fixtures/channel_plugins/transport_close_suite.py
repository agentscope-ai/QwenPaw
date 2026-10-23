# -*- coding: utf-8 -*-
# pylint: disable=missing-function-docstring,missing-class-docstring
# pylint: disable=protected-access
"""A transport owns its wait task; the protocol owns the close Future."""

import asyncio
import gc

import pytest

from qwenpaw.plugins.execution.framing import FramedTransport, FramingLimits


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cause",
    ["timeout", "outer-cancellation", "late-close-error"],
)
async def test_close_preserves_protocol_owned_waiter(cause):
    loop = asyncio.get_running_loop()
    errors = []
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: errors.append(context))
    protocol_closed = loop.create_future()
    entered = asyncio.Event()

    class Writer:
        def close(self):
            pass

        async def wait_closed(self):
            entered.set()
            # asyncio StreamWriter's wait_closed awaits this same shared
            # protocol-owned Future. A late pipe callback completes it.
            await protocol_closed

    transport = FramedTransport(
        asyncio.StreamReader(),
        Writer(),
        limits=FramingLimits(write_timeout=0.02),
    )
    closing = asyncio.create_task(transport.aclose())
    try:
        await entered.wait()
        if cause == "outer-cancellation":
            closing.cancel()
        await asyncio.gather(closing, return_exceptions=True)
        assert transport._writer_task.done(), "close leaked writer task"
        assert (
            not protocol_closed.cancelled()
        ), "close cancelled protocol Future"
        if cause == "late-close-error":
            loop.call_soon(
                protocol_closed.set_exception,
                OSError("controlled late pipe close error"),
            )
        else:
            loop.call_soon(protocol_closed.set_result, None)
        await asyncio.sleep(0.02)
        assert transport._writer_close_task.done()
        # Task exception reporting is deferred until the last strong reference
        # disappears. Keep our loop handler installed while forcing that point.
        transport._writer_close_task = None
        gc.collect()
        await asyncio.sleep(0)
        assert not errors, errors
    finally:
        if not protocol_closed.done():
            protocol_closed.set_result(None)
        transport._writer_task.cancel()
        await asyncio.gather(transport._writer_task, return_exceptions=True)
        loop.set_exception_handler(old_handler)
