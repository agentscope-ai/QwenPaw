# -*- coding: utf-8 -*-
"""Cross-process advisory lock for plugin dependency installation.

The plugin loader installs third-party Python dependencies with
``pip install`` / ``pip install --target``. In the frozen desktop build
several backend processes can run at once (e.g. an orphaned backend left
over from a crash plus a freshly launched one — see issue #5550). Without
a lock they each spawn ``pip install`` for the *same* requirements into the
*same* target directory at the same time. That both wastes hundreds of MB
per ``pip`` process (OOM risk) and corrupts the shared ``.dist-info``,
which makes the next "is this dependency satisfied?" probe fail and trigger
yet another reinstall — a self-amplifying loop.

This module provides a small, dependency-free advisory file lock that is
automatically released when the holding process exits (even on crash),
because it relies on OS-level locking (``fcntl.flock`` / ``msvcrt.locking``)
rather than the mere existence of a lock file.
"""

from __future__ import annotations

import contextlib
import errno
import logging
import os
import time
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

# Poll interval while waiting for a contended lock.
_RETRY_INTERVAL_SECONDS = 0.25


def _acquire_os_lock(fd: int) -> bool:
    """Try once to take an exclusive, non-blocking lock on *fd*.

    Returns ``True`` on success, ``False`` if another process holds it.
    Re-raises unexpected OS errors.
    """
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError as exc:
            # EACCES/EDEADLOCK == already locked by someone else.
            if exc.errno in (errno.EACCES, errno.EDEADLOCK):
                return False
            raise
    else:
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                return False
            raise


def _release_os_lock(fd: int) -> None:
    """Best-effort release of the lock held on *fd*."""
    try:
        if os.name == "nt":
            import msvcrt

            # The file offset must match the one used when locking.
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        logger.debug("Failed to release plugin install lock", exc_info=True)


@contextlib.contextmanager
def plugin_install_lock(
    lock_path: Path,
    *,
    timeout: float = 300.0,
) -> Iterator[bool]:
    """Hold an inter-process lock for the duration of the ``with`` block.

    Args:
        lock_path: Path to the lock file. Parent dirs are created.
        timeout: Seconds to wait for the lock before giving up. The block
            still runs when the wait times out (the install proceeds
            unlocked rather than being skipped), so a stuck peer can never
            permanently block a plugin from installing its dependencies.

    Yields:
        ``True`` if the lock was acquired, ``False`` if the wait timed out
        and the body runs without the lock.
    """
    lock_path = Path(lock_path)
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.debug(
            "Could not create lock dir for %s; proceeding without lock",
            lock_path,
            exc_info=True,
        )
        yield False
        return

    try:
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        logger.debug(
            "Could not open lock file %s; proceeding without lock",
            lock_path,
            exc_info=True,
        )
        yield False
        return

    acquired = False
    deadline = time.monotonic() + max(timeout, 0.0)
    try:
        while True:
            try:
                acquired = _acquire_os_lock(fd)
            except OSError:
                logger.debug(
                    "Unexpected error locking %s; proceeding without lock",
                    lock_path,
                    exc_info=True,
                )
                acquired = False
                break
            if acquired or time.monotonic() >= deadline:
                break
            time.sleep(_RETRY_INTERVAL_SECONDS)

        if not acquired:
            logger.warning(
                "Timed out after %.0fs waiting for plugin install lock %s; "
                "proceeding without it",
                timeout,
                lock_path,
            )
        yield acquired
    finally:
        if acquired:
            _release_os_lock(fd)
        with contextlib.suppress(OSError):
            os.close(fd)
