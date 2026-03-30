# -*- coding: utf-8 -*-
import asyncio

import pytest

from copaw.app.runner.task_tracker import TaskTracker


@pytest.mark.asyncio
async def test_start_or_queue_serializes_same_run_key() -> None:
    tracker = TaskTracker()
    first_started = asyncio.Event()
    finish_first = asyncio.Event()
    second_started = asyncio.Event()

    async def stream_fn(payload: str):
        if payload == "first":
            first_started.set()
            await finish_first.wait()
        else:
            second_started.set()
        yield f"data: {payload}\n\n"

    first_queue = await tracker.start_or_queue("chat-1", "first", stream_fn)
    await first_started.wait()

    second_queue = await tracker.start_or_queue("chat-1", "second", stream_fn)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(second_queue.get(), timeout=0.2)

    finish_first.set()

    assert (
        await asyncio.wait_for(first_queue.get(), timeout=1)
        == "data: first\n\n"
    )
    assert await asyncio.wait_for(first_queue.get(), timeout=1) is None

    await asyncio.wait_for(second_started.wait(), timeout=1)
    assert (
        await asyncio.wait_for(second_queue.get(), timeout=1)
        == "data: second\n\n"
    )
    assert await asyncio.wait_for(second_queue.get(), timeout=1) is None
