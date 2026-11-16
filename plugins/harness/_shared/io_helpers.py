# -*- coding: utf-8 -*-
"""Bounded plugin I/O that completes before its owner releases a lock."""

import asyncio


async def finish(operation):
    """Wait for actual completion before propagating caller cancellation."""
    task = asyncio.ensure_future(operation)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except BaseException:
            if not cancelled:
                raise
            break
    if cancelled:
        try:
            task.result()
        except BaseException:
            pass
        raise asyncio.CancelledError
    return task.result()


async def run_io(operation, *args, **kwargs):
    """Offload one bounded filesystem/discovery transaction, never clients."""
    return await finish(asyncio.to_thread(operation, *args, **kwargs))


async def stop_process(process, *, drain=False):
    """Terminate and reap an owned process without deleting native state."""
    if process.returncode is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass

    async def reap():
        if drain:
            await process.communicate()
        return await process.wait()

    try:
        await asyncio.wait_for(reap(), timeout=5)
    except asyncio.TimeoutError:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        # If inherited pipes never close, fail boundedly; the backend retains
        # the process handle for retry rather than declaring it released.
        await asyncio.wait_for(reap(), timeout=5)
