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
import asyncio
import errno
import logging
import os
import time
from weakref import WeakKeyDictionary
from pathlib import Path
from typing import Iterator

from .execution.dependencies import canonical_environment_path

logger = logging.getLogger(__name__)

_environment_locks: WeakKeyDictionary = WeakKeyDictionary()


@contextlib.asynccontextmanager
async def async_lock(lock):
    """Settle threaded acquisition before cancellation releases custody."""
    from .execution.process import _settle

    acquisition = asyncio.create_task(asyncio.to_thread(lock.__enter__))
    try:
        await asyncio.shield(acquisition)
    except asyncio.CancelledError:
        try:
            await _settle(acquisition)
        finally:
            if not acquisition.cancelled() and acquisition.exception() is None:
                lock.__exit__(None, None, None)
        raise
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


@contextlib.asynccontextmanager
async def environment_coordinator(targets):
    """Serialize overlapping in-process admissions and publications."""
    keys = sorted({canonical_environment_path(path) for path in targets})
    locks = _environment_locks.setdefault(asyncio.get_running_loop(), {})
    async with contextlib.AsyncExitStack() as stack:
        for key in keys:
            await stack.enter_async_context(
                locks.setdefault(key, asyncio.Lock()),
            )
        yield


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


class InstallLockError(RuntimeError):
    """No shared dependency writes are permitted without exclusion."""

    reason_code = "INSTALL_LOCK_UNAVAILABLE"


def environment_install_lock_path(target: Path) -> Path:
    """Key exclusion by the canonical write destination, across workspaces."""
    root = canonical_environment_path(target)
    return root.parent / f".{root.name}.dependencies.lock"


@contextlib.contextmanager
def plugin_install_lock(
    lock_path: Path,
    *,
    timeout: float = 300.0,
) -> Iterator[bool]:
    """Yield True only while holding exclusion; acquisition fails closed."""
    lock_path = Path(lock_path)
    suffix = ".dependencies.lock"
    site = (
        lock_path.parent / lock_path.name[1 : -len(suffix)]
        if lock_path.name.startswith(".") and lock_path.name.endswith(suffix)
        else None
    )
    if site is not None:
        from .dependency_maintenance import check_admission

        # An in-flight additive writer owns its repair marker. Wait for its
        # exclusion before classifying that marker as inherited damage.
        check_admission(site, check_repair=False)
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise InstallLockError("INSTALL_LOCK_UNAVAILABLE") from exc
    acquired = False
    deadline = time.monotonic() + max(timeout, 0.0)
    try:
        try:
            if os.name == "nt" and os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            while True:
                os.lseek(fd, 0, os.SEEK_SET)
                acquired = _acquire_os_lock(fd)
                if acquired:
                    break
                if time.monotonic() >= deadline:
                    raise InstallLockError("INSTALL_LOCK_UNAVAILABLE")
                time.sleep(
                    min(
                        _RETRY_INTERVAL_SECONDS,
                        max(0, deadline - time.monotonic()),
                    ),
                )
        except OSError as exc:
            raise InstallLockError("INSTALL_LOCK_UNAVAILABLE") from exc
        if site is not None:
            check_admission(site)
        yield True
    finally:
        if acquired:
            _release_os_lock(fd)
        with contextlib.suppress(OSError):
            os.close(fd)
