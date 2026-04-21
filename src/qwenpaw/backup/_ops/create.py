# -*- coding: utf-8 -*-
"""Backup creation: sync and SSE streaming."""
from __future__ import annotations

import asyncio
import logging
import threading
import zipfile
from typing import Any, AsyncGenerator

from .._utils.constants import META_FILE, zip_path
from .._utils.meta import finalize_backup_meta
from ..models import BackupMeta, CreateBackupRequest
from ...config.utils import load_config
from ...constant import BACKUP_DIR
from .create_helpers import add_files_to_zip

logger = logging.getLogger(__name__)


async def create_stream(
    req: CreateBackupRequest,
) -> AsyncGenerator[dict, None]:
    """Create a backup and yield progress events for SSE streaming.

    Compression runs in a background thread; events are delivered via an
    ``asyncio.Queue`` using ``loop.call_soon_threadsafe`` so the event loop
    is never blocked by a busy-wait.  When the client disconnects,
    ``stop_event`` is set so the thread exits at the next cancellation point.

    Event shapes:
      {"type": "start",     "total_agents": N, "percent": 0}
      {"type": "agent",     "agent_id": str, "index": int,
                            "total": int, "percent": int}
      {"type": "saving",    "percent": 90}
      {"type": "done",      "meta": dict, "percent": 100}
      {"type": "error",     "message": str}
    """
    meta = BackupMeta(
        name=req.name,
        description=req.description,
        scope=req.scope,
    )
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    loop = asyncio.get_running_loop()
    # asyncio.Queue is used for the consumer side (async); the background
    # thread pushes events via loop.call_soon_threadsafe so no blocking occurs.
    q: asyncio.Queue[dict | None] = asyncio.Queue()
    stop_event = threading.Event()

    def _put(event: dict | None) -> None:
        loop.call_soon_threadsafe(q.put_nowait, event)

    task = asyncio.create_task(
        asyncio.to_thread(
            _create_with_progress,
            meta,
            req.agents,
            _put,
            stop_event,
        ),
    )
    try:
        while True:
            event = await q.get()
            if event is None:  # sentinel – thread finished
                break
            yield event
    except (asyncio.CancelledError, GeneratorExit):
        # Client disconnected: signal thread to stop at next cancellation
        # point.
        stop_event.set()
        raise
    finally:
        # Wait for thread to finish; shield prevents task from being abandoned.
        try:
            await asyncio.shield(task)
        except (asyncio.CancelledError, Exception):
            pass


def _compute_initial_agents(
    req_agents: list[str],
    config,
) -> tuple[list[tuple[str, Any]], list[str]]:
    """Return ``((agent_id, profile_ref) pairs, missing_agent_ids)``.

    Only agents that exist in the current config are included in the first
    list; IDs not found in the config are returned as *missing_agent_ids*
    (the agent may have been deleted since the backup scope was defined).
    """
    valid: list[tuple[str, Any]] = []
    missing: list[str] = []
    for aid in req_agents:
        ref = config.agents.profiles.get(aid)
        if ref is not None:
            valid.append((aid, ref))
        else:
            missing.append(aid)
    return valid, missing


def _write_meta_and_finalize(
    zf: zipfile.ZipFile,
    meta: BackupMeta,
    agent_count: int,
    put: Any,
) -> None:
    """Finalize *meta*, emit a saving event, and write meta.json into *zf*."""
    finalize_backup_meta(meta, agent_count)
    put({"type": "saving", "percent": 90})
    zf.writestr(META_FILE, meta.model_dump_json(indent=2))


def _create_with_progress(
    meta: BackupMeta,
    req_agents: list[str],
    put: Any,
    stop_event: threading.Event,
) -> None:
    """Run compression in a sync thread and emit progress events via *put*.

    *put* is a thread-safe callable that pushes an event (or ``None``
    sentinel) into the async consumer queue via
    ``loop.call_soon_threadsafe``.

    Writes directly to a .tmp file (no in-memory accumulation), then
    atomically replaces the final .zip on success. If stop_event is set
    the thread exits at the next cancellation point without writing the file.
    """
    try:
        dest = zip_path(meta.id)
        tmp = dest.with_suffix(".tmp")
        try:
            _compress_to_tmp(meta, req_agents, put, stop_event, tmp, dest)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    except Exception as exc:
        logger.exception("Backup creation failed for %s", meta.id)
        put({"type": "error", "message": str(exc)})
    finally:
        put(None)  # sentinel – signals the generator loop to exit


def _compress_to_tmp(
    meta: BackupMeta,
    req_agents: list[str],
    put: Any,
    stop_event: threading.Event,
    tmp,
    dest,
) -> None:
    """Write backup zip to *tmp* and atomically replace *dest* on success."""
    # Remove any pre-existing tmp file from a previous crashed run so that
    # zipfile.ZipFile(..., "w") starts from a clean slate.  On Windows an
    # open handle on this path would raise OSError here rather than
    # silently appending to a stale file.
    tmp.unlink(missing_ok=True)
    cancelled = False
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        config = load_config()
        if meta.scope.include_agents:
            valid_agents, missing_agents = _compute_initial_agents(
                req_agents,
                config,
            )
        else:
            valid_agents, missing_agents = [], []
        put(
            {"type": "start", "total_agents": len(valid_agents), "percent": 0},
        )
        if missing_agents:
            logger.warning(
                "Skipping agents not found in config: %s",
                missing_agents,
            )

        def progress_callback(current, total, agent_id):
            percent = int(10 + 75 * current / max(total, 1))
            put(
                {
                    "type": "agent",
                    "agent_id": agent_id,
                    "index": current,
                    "total": total,
                    "percent": percent,
                },
            )

        backed_up_agents = add_files_to_zip(
            zf,
            meta,
            progress_callback,
            stop_event,
            valid_agents=valid_agents,
        )

        if stop_event.is_set():
            # Mark cancelled; unlink tmp after the with block closes the file
            # (unlinking an open file fails on Windows).
            cancelled = True
        else:
            _write_meta_and_finalize(zf, meta, len(backed_up_agents), put)

    if cancelled:
        tmp.unlink(missing_ok=True)
        logger.info(
            "Backup creation cancelled by client (backup_id=%s)",
            meta.id,
        )
        return

    tmp.replace(dest)  # atomic on both Windows and Linux
    put(
        {"type": "done", "meta": meta.model_dump(mode="json"), "percent": 100},
    )
