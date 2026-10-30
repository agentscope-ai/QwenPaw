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
_observations: WeakKeyDictionary = WeakKeyDictionary()
_observation_inputs: WeakKeyDictionary = WeakKeyDictionary()


def observation_inputs():
    """Only the task holding exclusion may lend its raw input store."""
    return _observation_inputs.get(asyncio.current_task())


@contextlib.contextmanager
def observation_write():
    """Discard raw read inputs around a real publication or restoration."""
    inputs = observation_inputs()
    if inputs is not None:
        inputs.clear()
    try:
        yield
    finally:
        if inputs is not None:
            inputs.clear()


@contextlib.asynccontextmanager
async def async_lock(lock, *, on_acquired=None):
    """Settle fd-based entry and exit; never use thread-affine contexts.

    The custody callback runs in the original task even on late acquisition.
    """
    import sys
    from ..utils.io_utils import run_sync_io

    acquisition = asyncio.create_task(run_sync_io(lock.__enter__))
    cancelled = False
    while not acquisition.done():
        try:
            await asyncio.shield(acquisition)
        except asyncio.CancelledError:
            cancelled = True
        except BaseException:
            break
    if cancelled:
        if not acquisition.cancelled() and acquisition.exception() is None:
            try:
                if on_acquired is not None:
                    on_acquired(acquisition.result())
            finally:
                await run_sync_io(lock.__exit__, None, None, None)
        raise asyncio.CancelledError
    value = acquisition.result()
    try:
        if on_acquired is not None:
            on_acquired(value)
        yield value
    except BaseException:
        if not await run_sync_io(lock.__exit__, *sys.exc_info()):
            raise
    else:
        await run_sync_io(lock.__exit__, None, None, None)


@contextlib.asynccontextmanager
async def environment_coordinator(targets):
    """Serialize overlapping in-process admissions and publications."""
    from ..utils.io_utils import run_sync_io

    targets = tuple(targets)

    def identities():
        roots = [canonical_environment_path(path) for path in targets]
        if any(not root.is_dir() for root in roots):
            raise RuntimeError("DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED")
        return sorted({str(root) for root in roots})

    keys = await run_sync_io(identities)
    locks = _environment_locks.setdefault(asyncio.get_running_loop(), {})
    async with contextlib.AsyncExitStack() as stack:
        for key in keys:
            await stack.enter_async_context(
                locks.setdefault(key, asyncio.Lock()),
            )
        yield


class ObservationRootsChanged(RuntimeError):
    """Release the current observation before preparing these roots."""

    def __init__(self, targets):
        self.targets = targets
        super().__init__("DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED")


@contextlib.asynccontextmanager
async def environment_observation(targets, *, timeout=300.0):
    """Read and admit under ordered process and OS exclusion.

    Only the current task can reuse its live scope, and only for covered
    roots. A changed root set must release and prepare again; neither child
    tasks nor an inherited context variable confer lock ownership.
    """
    from ..utils.io_utils import run_sync_io

    targets = tuple(targets)
    keys = frozenset(
        await run_sync_io(
            lambda: {str(canonical_environment_path(p)) for p in targets},
        ),
    )
    task = asyncio.current_task()
    held = _observations.get(task)
    if held is not None:
        if not keys <= held:
            raise ObservationRootsChanged(keys)
        yield
        return
    async with (
        environment_coordinator(keys),
        contextlib.AsyncExitStack() as stack,
    ):
        for key in sorted(keys):
            path = await run_sync_io(environment_install_lock_path, Path(key))
            await stack.enter_async_context(
                async_lock(plugin_install_lock(path, timeout=timeout)),
            )

        def validate():
            if {
                str(canonical_environment_path(p)) for p in targets
            } != keys or any(
                str(canonical_environment_path(p)) != p or not Path(p).is_dir()
                for p in keys
            ):
                raise RuntimeError("DEPENDENCY_ENVIRONMENT_IDENTITY_CHANGED")

        await run_sync_io(validate)
        from .dependency_maintenance import observation_readers

        await stack.enter_async_context(async_lock(observation_readers(keys)))
        _observations[task] = keys
        _observation_inputs[task] = {}
        try:
            yield
        finally:
            del _observations[task]
            del _observation_inputs[task]


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
    from .dependency_maintenance import _gate

    return _gate(target)


@contextlib.contextmanager
def plugin_install_lock(
    lock_path: Path,
    *,
    timeout: float = 300.0,
) -> Iterator[bool]:
    """Yield True only while holding exclusion; acquisition fails closed."""
    lock_path = Path(lock_path)
    suffix = ".dependencies.lock"
    environment_lock = lock_path.name.startswith(
        ".",
    ) and lock_path.name.endswith(suffix)
    if environment_lock:
        from .dependency_maintenance import check_lock_admission

        # Wait for an additive writer before classifying its repair marker.
        check_lock_admission(lock_path, check_repair=False)
    try:
        if environment_lock:
            from .dependency_maintenance import open_coordination_lock

            fd = open_coordination_lock(lock_path)
        else:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise InstallLockError("INSTALL_LOCK_UNAVAILABLE") from exc
    acquired = False
    deadline = time.monotonic() + max(timeout, 0.0)
    try:
        try:
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
        if environment_lock:
            check_lock_admission(lock_path)
        yield True
    finally:
        if acquired:
            _release_os_lock(fd)
        with contextlib.suppress(OSError):
            os.close(fd)
