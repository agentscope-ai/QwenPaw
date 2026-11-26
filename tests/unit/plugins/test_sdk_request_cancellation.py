# -*- coding: utf-8 -*-
"""Disconnects await callback cleanup without consuming external cancellation."""

import asyncio

import pytest
from starlette.requests import Request

from qwenpaw.utils.request_cancellation import (
    ClientDisconnected,
    cancel_on_disconnect,
)


@pytest.mark.parametrize("disconnect", [True, False])
async def test_cancellation_waits_for_callback_cleanup(disconnect):
    messages = asyncio.Queue()
    request = Request({"type": "http"}, receive=messages.get)
    entered, cleaning, release = (asyncio.Event() for _ in range(3))

    async def handle():
        async with cancel_on_disconnect(request):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()

    task = asyncio.create_task(handle())
    try:
        await asyncio.wait_for(entered.wait(), 2)
        if disconnect:
            await messages.put({"type": "http.disconnect"})
        else:
            task.cancel()
        await asyncio.wait_for(cleaning.wait(), 2)
        assert not task.done()
        release.set()
        with pytest.raises(
            ClientDisconnected if disconnect else asyncio.CancelledError,
        ):
            await asyncio.wait_for(task, 2)
        assert not any(
            t.get_name() == "http-disconnect" for t in asyncio.all_tasks()
        )
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
