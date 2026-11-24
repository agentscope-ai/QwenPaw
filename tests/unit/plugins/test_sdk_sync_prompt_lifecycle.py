# -*- coding: utf-8 -*-
"""Prompt callbacks in worker threads must retain lifecycle ownership."""

import asyncio
import threading

import pytest

from qwenpaw.plugins.activity import PluginActivity, PluginBusyError


async def test_sync_callback_blocks_replacement_until_thread_exits():
    activity = PluginActivity("prompt-owner")
    entered, release = threading.Event(), threading.Event()

    def callback():
        with activity.sync_invocation():
            entered.set()
            assert release.wait(5)

    task = asyncio.create_task(asyncio.to_thread(callback))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        for interrupt in (False, True):
            with pytest.raises(PluginBusyError) as error:
                async with activity.mutation(interrupt_tasks=interrupt):
                    pytest.fail("replaced resources while callback was alive")
            assert error.value.detail["quiescent"] is False
    finally:
        release.set()
        await task
    async with activity.mutation():
        with pytest.raises(PluginBusyError):
            await asyncio.to_thread(callback)
    assert activity.sync_calls == 0
