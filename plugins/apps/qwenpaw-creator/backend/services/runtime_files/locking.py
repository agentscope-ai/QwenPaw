# -*- coding: utf-8 -*-
"""Short cross-process locks for filesystem Runtime stores.

Lock files are stable coordination inodes and are intentionally never unlinked
after release.  Removing an advisory lock file can create two lock domains when
one process still has the old inode open.
"""

from __future__ import annotations

import errno
import logging
import os
from pathlib import Path
import time
from types import TracebackType

from .errors import LockTimeoutError, RuntimeFileValidationError

logger = logging.getLogger("qwenpaw.creator.runtime_files.locking")

if os.name == "nt":  # pragma: posix no cover
    import msvcrt

    def _try_lock(descriptor: int, *, shared: bool) -> None:
        """Windows byte-range lock; shared degrades to exclusive.

        ``msvcrt.locking`` exposes only exclusive region locks, so reader
        locks serialize on Windows.  Correctness (mutual exclusion with
        writers) is preserved; only reader concurrency is reduced.
        """

        del shared
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)

    def _unlock(descriptor: int) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)

    _BLOCKED_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN, errno.EDEADLK})
else:
    import fcntl

    def _try_lock(descriptor: int, *, shared: bool) -> None:
        lock_op = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        fcntl.flock(descriptor, lock_op | fcntl.LOCK_NB)

    def _unlock(descriptor: int) -> None:
        fcntl.flock(descriptor, fcntl.LOCK_UN)

    _BLOCKED_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN})


class CrossProcessFileLock:
    """An exclusive, process-crash-safe cross-platform file lock.

    POSIX uses ``fcntl.flock``; Windows uses ``msvcrt.locking`` byte-range
    locks.  The lock only protects writers that share this primitive.  Runtime
    locks must therefore be acquired at a single documented boundary and kept
    out of model/provider calls.  The operating system releases the lock when
    the descriptor or process exits; the file itself contains no authoritative
    state.

    Pass ``shared=True`` for a ``LOCK_SH`` reader lock.  On POSIX reader locks
    do not block each other, so concurrent read-only polling never serializes
    against itself; they still exclude ``LOCK_EX`` writers (and vice versa).
    POSIX ``flock`` merges multiple descriptors on the same inode within one
    process, so reader locks are safe across threads of the same process.  On
    Windows shared locks degrade to exclusive locks.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        timeout_seconds: float | None = 10.0,
        poll_interval_seconds: float = 0.01,
        mode: int = 0o600,
        shared: bool = False,
    ) -> None:
        self.path = Path(path)
        if timeout_seconds is not None and timeout_seconds < 0:
            raise RuntimeFileValidationError(
                "lock timeout must be non-negative or None",
            )
        if poll_interval_seconds <= 0:
            raise RuntimeFileValidationError(
                "lock poll interval must be positive",
            )
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.mode = mode
        self.shared = shared
        self._descriptor: int | None = None

    def acquired(self) -> bool:
        return self._descriptor is not None

    def _log_acquired(self, elapsed: float) -> None:
        if elapsed > 0.5:
            logger.warning(
                "acquired lock %s after %.2fs (shared=%s)",
                self.path,
                elapsed,
                self.shared,
            )
        else:
            logger.debug(
                "acquired lock %s (shared=%s)",
                self.path,
                self.shared,
            )

    def acquire(self) -> CrossProcessFileLock:
        if self._descriptor is not None:
            raise RuntimeFileValidationError(
                f"lock is not re-entrant: {self.path}",
            )

        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.path, flags, self.mode)
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, self.mode)
        started = time.monotonic()
        try:
            while True:
                try:
                    _try_lock(descriptor, shared=self.shared)
                    self._descriptor = descriptor
                    self._log_acquired(time.monotonic() - started)
                    return self
                except OSError as exc:
                    if exc.errno not in _BLOCKED_ERRNOS:
                        raise
                if self.timeout_seconds is not None:
                    elapsed = time.monotonic() - started
                    if elapsed >= self.timeout_seconds:
                        logger.warning(
                            "lock %s timed out after %.2fs",
                            self.path,
                            elapsed,
                        )
                        raise LockTimeoutError(self.path, self.timeout_seconds)
                    remaining = self.timeout_seconds - elapsed
                    time.sleep(min(self.poll_interval_seconds, remaining))
                else:
                    time.sleep(self.poll_interval_seconds)
        except BaseException:
            os.close(descriptor)
            raise

    def release(self) -> None:
        descriptor = self._descriptor
        if descriptor is None:
            return
        self._descriptor = None
        try:
            _unlock(descriptor)
            logger.debug("released lock %s", self.path)
        finally:
            os.close(descriptor)

    def __enter__(self) -> CrossProcessFileLock:
        return self.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.release()
