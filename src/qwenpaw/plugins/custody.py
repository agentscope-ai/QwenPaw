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

logger = logging.getLogger(__name__)

TASK_STOP_SECONDS = 5.0
THREAD_STOP_SECONDS = 5.0
PROCESS_STOP_SECONDS = 10.0
WATCH_STOP_SECONDS = 5.0
CONNECTION_STOP_SECONDS = 5.0


async def stop_task(task: asyncio.Task[Any], desc: str) -> None:
    """Cancel *task* and wait until it finishes."""
    if task.done():
        return
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=TASK_STOP_SECONDS)
    except asyncio.CancelledError:
        return
    except asyncio.TimeoutError as exc:
        raise TimeoutError(
            f"task {desc!r} did not stop in {TASK_STOP_SECONDS:.0f}s",
        ) from exc


def stop_thread(
    thread: threading.Thread,
    stop: threading.Event | None,
    desc: str,
) -> None:
    """Signal *stop* and join *thread*."""
    if stop is not None:
        stop.set()
    thread.join(timeout=THREAD_STOP_SECONDS)
    if thread.is_alive():
        raise TimeoutError(
            f"thread {desc!r} did not stop in {THREAD_STOP_SECONDS:.0f}s",
        )


def stop_subprocess(proc: Any, desc: str) -> None:
    """Close pipes, terminate, wait, then kill if needed."""
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


async def close_connection(client: Any, desc: str) -> None:
    """Await ``aclose`` / ``close`` on *client*."""
    closer = getattr(client, "aclose", None) or getattr(client, "close", None)
    if closer is None:
        return
    result = closer()
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


def scan_unhosted_tasks(plugin_id: str) -> list[str]:
    """List running tasks whose coroutine module belongs to *plugin_id*."""
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
        module = getattr(coro, "__module__", "") or ""
        if module == prefix or module.startswith(prefix + "."):
            leftovers.append(
                f"unhosted_task:{task.get_name()}:{module}",
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
