# -*- coding: utf-8 -*-
"""Teardown helpers for plugin-owned background resources."""

from __future__ import annotations

import asyncio
import inspect
import logging
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

from ..utils.io_utils import run_sync_io

logger = logging.getLogger(__name__)

TASK_STOP_SECONDS = 5.0
THREAD_STOP_SECONDS = 5.0
PROCESS_STOP_SECONDS = 10.0
WATCH_STOP_SECONDS = 5.0
CONNECTION_STOP_SECONDS = 5.0


async def stop_task(task: asyncio.Task[Any], desc: str) -> None:
    """Cancel *task* and wait until it finishes or the budget expires."""
    if task.done():
        return
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=TASK_STOP_SECONDS)
    except asyncio.CancelledError:
        return
    except asyncio.TimeoutError as exc:
        raise TimeoutError(
            f"task {desc!r} did not stop in {TASK_STOP_SECONDS:.0f}s "
            "(wait_for waited for cancellation to complete)",
        ) from exc


def _stop_thread_blocking(
    thread: threading.Thread,
    stop: threading.Event | None,
    desc: str,
) -> None:
    if stop is not None:
        stop.set()
    thread.join(timeout=THREAD_STOP_SECONDS)
    if thread.is_alive():
        raise TimeoutError(
            f"thread {desc!r} did not stop in {THREAD_STOP_SECONDS:.0f}s",
        )


async def stop_thread(
    thread: threading.Thread,
    stop: threading.Event | None,
    desc: str,
) -> None:
    """Signal *stop* and join *thread* off the event loop."""
    await run_sync_io(_stop_thread_blocking, thread, stop, desc)


def _stop_subprocess_blocking(proc: Any, desc: str) -> None:
    for stream in (
        getattr(proc, "stdout", None),
        getattr(proc, "stderr", None),
    ):
        if stream is None:
            continue
        closer = getattr(stream, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:  # noqa: BLE001
                logger.debug("Failed to close pipe for %s", desc)
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=PROCESS_STOP_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=PROCESS_STOP_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                f"subprocess {desc!r} did not exit "
                f"in {PROCESS_STOP_SECONDS:.0f}s",
            ) from exc


async def stop_subprocess(proc: Any, desc: str) -> None:
    """Close pipes, terminate, wait, then kill if needed — off the loop."""
    await run_sync_io(_stop_subprocess_blocking, proc, desc)


async def close_connection(client: Any, desc: str) -> None:
    """Close *client*. Await ``aclose``; run sync ``close`` in a thread."""
    aclose = getattr(client, "aclose", None)
    if callable(aclose):
        result = aclose()
        if inspect.isawaitable(result):
            try:
                await asyncio.wait_for(
                    result,
                    timeout=CONNECTION_STOP_SECONDS,
                )
            except asyncio.TimeoutError as exc:
                raise TimeoutError(
                    f"connection {desc!r} did not close "
                    f"in {CONNECTION_STOP_SECONDS:.0f}s",
                ) from exc
        return
    closer = getattr(client, "close", None)
    if closer is None:
        return
    if inspect.iscoroutinefunction(closer):
        try:
            await asyncio.wait_for(
                closer(),
                timeout=CONNECTION_STOP_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"connection {desc!r} did not close "
                f"in {CONNECTION_STOP_SECONDS:.0f}s",
            ) from exc
        return
    await run_sync_io(closer)


def start_watch(
    path: Path,
    on_event: Callable[[str], Any],
    stop: threading.Event,
    generation: int,
    current_generation: Callable[[], int],
) -> threading.Thread:
    """Poll *path* and invoke *on_event* until *stop* is set."""

    def _loop() -> None:
        last = _mtime(path)
        while not stop.wait(1.0):
            if current_generation() != generation:
                logger.warning(
                    "Dropping stale watch callback for %s",
                    path,
                )
                return
            now = _mtime(path)
            if now != last:
                last = now
                try:
                    on_event(str(path))
                except Exception:  # noqa: BLE001
                    logger.exception("Watch callback failed for %s", path)

    thread = threading.Thread(
        target=_loop,
        name=f"plugin-watch-{path.name}",
        daemon=True,
    )
    thread.start()
    return thread


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _coro_owner_module(coro: Any) -> str:
    """Best-effort module name from frame / code, not ``coro.__module__``."""
    frame = getattr(coro, "cr_frame", None) or getattr(coro, "gi_frame", None)
    if frame is not None:
        name = (frame.f_globals or {}).get("__name__", "") or ""
        if name:
            return str(name)
    code = getattr(coro, "cr_code", None) or getattr(coro, "gi_code", None)
    if code is None:
        return ""
    filename = getattr(code, "co_filename", "") or ""
    return str(filename)


def scan_unhosted_tasks(plugin_id: str) -> list[str]:
    """List running tasks whose coroutine belongs to *plugin_id*."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return []
    prefix = f"plugin_{plugin_id.replace('-', '_')}"
    leftovers: list[str] = []
    for task in asyncio.all_tasks(loop):
        if task.done():
            continue
        coro = task.get_coro()
        owner = _coro_owner_module(coro)
        if (
            owner == prefix
            or owner.startswith(prefix + ".")
            or (prefix in owner.replace("-", "_") and owner.endswith(".py"))
        ):
            leftovers.append(
                f"unhosted_task:{task.get_name()}:{owner}",
            )
    return leftovers


def wrap_task_body(
    coro: Any,
    *,
    instance: Any,
    generation: int,
    desc: str,
) -> Any:
    """Run *coro*, discard stale generations, record uncaught errors."""

    async def _runner() -> None:
        if instance.generation != generation:
            logger.warning(
                "Dropping stale task %r for plugin '%s'",
                desc,
                instance.plugin_id,
            )
            if inspect.iscoroutine(coro):
                coro.close()
            return
        try:
            await coro
        except Exception:  # noqa: BLE001
            logger.error(
                "Hosted task %r for plugin '%s' crashed",
                desc,
                instance.plugin_id,
                exc_info=True,
            )
            instance.add_diagnostic("有托管任务异常退出")

    return _runner()
