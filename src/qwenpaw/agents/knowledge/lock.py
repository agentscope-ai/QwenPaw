# -*- coding: utf-8 -*-
"""Cross-process write lock for a shared knowledge base."""

from __future__ import annotations

import errno
import logging
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .store import kb_root, validate_kb_id

logger = logging.getLogger(__name__)

# Process-local locks keyed by resolved lock path (msvcrt is per-process).
_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class KnowledgeLockTimeout(TimeoutError):
    """Raised when the knowledge write lock cannot be acquired in time."""


def _thread_lock_for(path: Path) -> threading.Lock:
    # Always key by the parent-resolved string so a lock file that does not
    # exist yet and the same file after creation share one lock. The parent
    # dir is created before this call, so resolve() is stable.
    try:
        key = str(path.resolve())
    except OSError:
        key = str(path)
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[key] = lock
        return lock


def _try_acquire_os_lock(fd: int) -> bool:
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EDEADLOCK):
                return False
            raise
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            return False
        raise


def _release_os_lock(fd: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        logger.debug("Failed to release knowledge write lock", exc_info=True)


@contextmanager
def knowledge_write_lock(
    kb_id: str,
    *,
    timeout_s: float = 30.0,
    poll_s: float = 0.1,
) -> Iterator[Path]:
    """Acquire ``knowledge_bases/{id}/.locks/write.lock`` or time out.

    Yields the lock file path. On timeout raises
    :class:`KnowledgeLockTimeout` so callers skip catalog checkpointing.
    """
    kb_id = validate_kb_id(kb_id)
    lock_path = kb_root(kb_id) / ".locks" / "write.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    thread_lock = _thread_lock_for(lock_path)
    deadline = time.monotonic() + max(0.0, timeout_s)
    fd: int | None = None
    acquired = False

    while True:
        got_thread = thread_lock.acquire(blocking=False)
        if got_thread:
            try:
                # Ensure a lockable byte exists for msvcrt.
                with lock_path.open("a+b") as handle:
                    handle.seek(0)
                    if handle.read(1) == b"":
                        handle.write(b"0")
                        handle.flush()
                fd = os.open(str(lock_path), os.O_RDWR)
                if _try_acquire_os_lock(fd):
                    acquired = True
                    try:
                        yield lock_path
                    finally:
                        _release_os_lock(fd)
                        os.close(fd)
                        fd = None
                    return
                os.close(fd)
                fd = None
            finally:
                thread_lock.release()

        if time.monotonic() >= deadline:
            raise KnowledgeLockTimeout(
                f"Timed out acquiring knowledge write lock for {kb_id}",
            )
        time.sleep(poll_s)
