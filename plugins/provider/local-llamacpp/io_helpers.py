# -*- coding: utf-8 -*-
"""Blocking local I/O and bounded native process shutdown."""

import asyncio
import os
import signal
import subprocess


async def finish(operation):
    """Wait for completion before propagating caller cancellation."""
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
    return await finish(asyncio.to_thread(operation, *args, **kwargs))


def process_options():
    """Hide child consoles on Windows; give POSIX servers their own group."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def stop_server(process, *, graceful_timeout=5.0, kill_timeout=3.0):
    """Reap the server, retaining ownership if bounded shutdown fails."""
    for sig, timeout in (
        (signal.SIGTERM, graceful_timeout),
        (signal.SIGKILL if os.name != "nt" else None, kill_timeout),
    ):
        if process.poll() is not None:
            return
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(process.pid), sig)
            elif sig == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=timeout)
            return
        except subprocess.TimeoutExpired:
            pass
    raise RuntimeError("llama.cpp did not exit")


def stop_download(process, *, graceful_timeout=2.0, kill_timeout=2.0):
    """Terminate and reap a multiprocessing download worker."""
    if process.is_alive():
        process.terminate()
        process.join(timeout=graceful_timeout)
    if process.is_alive():
        process.kill()
        process.join(timeout=kill_timeout)
    if process.is_alive():
        raise RuntimeError("Download worker did not exit")
    process.join(timeout=0)
