# -*- coding: utf-8 -*-
"""Private resource custody for native calls; no process or IPC framework."""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit


async def cancel_tasks(tasks):
    """Join every owned task, including one already finishing cancellation."""
    tasks = [task for task in set(tasks) if task is not asyncio.current_task()]
    for task in tasks:
        if not task.done():
            task.cancel()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    failures = [
        r
        for r in results
        if isinstance(r, BaseException)
        and not isinstance(r, asyncio.CancelledError)
    ]
    if failures:
        raise RuntimeError("SIP_TASK_CLEANUP_FAILED") from failures[0]


async def run_native(function, *args, **kwargs):
    """Cancellation never abandons an already running native operation."""
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.shield(task)
        raise


class ResourceClaim:
    """Hold one native port or server/room claim until cleanup succeeds."""

    def __init__(
        self,
        url,
        room,
        *,
        reason_code="SIP_LIVEKIT_ROOM_ALREADY_OWNED",
    ):
        self.reason_code = reason_code
        parts = urlsplit(url)
        scheme = {"ws": "http", "wss": "https"}.get(
            parts.scheme.lower(),
            parts.scheme.lower(),
        )
        port = parts.port or (443 if scheme == "https" else 80)
        server = (
            scheme,
            parts.hostname.lower() if parts.hostname else "",
            port,
            parts.path.rstrip("/"),
        )
        key = hashlib.sha256((repr(server) + "\0" + room).encode()).hexdigest()
        root = Path(tempfile.gettempdir()) / "qwenpaw-sip-resource-claims"
        root.mkdir(mode=0o700, exist_ok=True)
        if root.is_symlink():
            raise RuntimeError("SIP_CLAIM_PATH_UNSAFE")
        self.path = root / (key + ".lock")
        self._fd = None

    def acquire(self):
        fd = os.open(
            self.path,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            raise RuntimeError(self.reason_code) from exc
        self._fd = fd

    def close(self):
        if self._fd is None:
            return
        fd = self._fd
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        self._fd = None
