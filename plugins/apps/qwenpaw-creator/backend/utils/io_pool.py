# -*- coding: utf-8 -*-
"""Optional sizing of the executor used by asyncio.to_thread."""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

IO_THREADS_ENV = "CREATOR_IO_THREADS"


def io_threads_from_env() -> int:
    """A positive explicit size enables the Creator executor."""
    try:
        return max(0, int(os.environ.get(IO_THREADS_ENV, "")))
    except ValueError:
        return 0


def configure_io_thread_pool() -> int:
    """Use a dedicated default executor only on an unconfigured loop."""
    workers = io_threads_from_env()
    if not workers:
        return 0
    loop = asyncio.get_running_loop()
    # asyncio exposes a setter but no getter for the existing host pool.
    # A loop with an unknown implementation retains its own executor.
    if getattr(loop, "_default_executor", True) is not None:
        return 0
    executor = ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="creator-io"
    )
    try:
        loop.set_default_executor(executor)
    except BaseException:
        executor.shutdown(wait=False)
        raise
    return workers
