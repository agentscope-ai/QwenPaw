# -*- coding: utf-8 -*-
"""Blocking local I/O and bounded native process shutdown."""

import asyncio
import os
import signal
import subprocess

# Keep the actual waits and the provider's enclosing deadline on one policy.
# Downloads stop their process before joining the monitor; server shutdown
# has a separate graceful-exit and forced-exit phase.
DOWNLOAD_PROCESS_WAIT_SECONDS = 2.0
DOWNLOAD_MONITOR_WAIT_SECONDS = 2.0
SERVER_GRACE_SECONDS = 5.0
SERVER_KILL_SECONDS = 3.0
DOWNLOAD_CLOSE_SECONDS = (
    2 * DOWNLOAD_PROCESS_WAIT_SECONDS + DOWNLOAD_MONITOR_WAIT_SECONDS
)
SERVER_CLOSE_SECONDS = SERVER_GRACE_SECONDS + SERVER_KILL_SECONDS
# Independent stops run concurrently. Reserve another 2s for executor handoff,
# log-task cancellation and final bookkeeping; slow I/O still hits this guard
# and leaves ownership intact for a retry rather than claiming quiescence.
PROVIDER_CLOSE_SECONDS = (
    max(DOWNLOAD_CLOSE_SECONDS, SERVER_CLOSE_SECONDS) + 2.0
)


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


def stop_server(
    process,
    graceful_timeout=SERVER_GRACE_SECONDS,
    kill_timeout=SERVER_KILL_SECONDS,
):
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


def stop_download(
    process,
    graceful_timeout=DOWNLOAD_PROCESS_WAIT_SECONDS,
    kill_timeout=DOWNLOAD_PROCESS_WAIT_SECONDS,
):
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
