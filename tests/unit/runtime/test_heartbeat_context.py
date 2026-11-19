import asyncio
from contextvars import ContextVar

import pytest

from qwenpaw.runtime.heartbeat import _HEARTBEAT_TICK, _iter_with_heartbeat


@pytest.mark.asyncio
async def test_stream_context_survives_idle_ticks_and_close():
    notice = ContextVar("notice", default=None)
    closed = []

    async def source():
        token = notice.set("local")
        try:
            yield 1
            await asyncio.sleep(.02)
            yield notice.get()
        finally:
            notice.reset(token)
            closed.append(True)

    stream = _iter_with_heartbeat(source(), .001)
    assert await anext(stream) == 1
    assert await anext(stream) is _HEARTBEAT_TICK
    async for value in stream:
        if value is not _HEARTBEAT_TICK:
            assert value == "local"
            break
    await stream.aclose()
    assert notice.get() is None and closed == [True]


@pytest.mark.asyncio
async def test_producer_timeout_is_not_mistaken_for_idle_heartbeat():
    async def source():
        yield 1
        raise TimeoutError("provider timed out")

    stream = _iter_with_heartbeat(source(), 5)
    assert await anext(stream) == 1
    with pytest.raises(TimeoutError, match="provider timed out"):
        await anext(stream)
